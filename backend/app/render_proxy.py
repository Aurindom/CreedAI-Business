"""Private leased CONNECT proxy: DNS checked once, public IP pinned, bytes/deadline bounded.

Chromium runs on internal-only networks. This is its sole Internet route.
No caller header, cookie, URL path or provider credential is logged or persisted.
"""
import asyncio
import base64
import hmac
import ipaddress
import json
import os
import secrets
import time
from dataclasses import dataclass,field
from urllib.parse import urlsplit

from .discovery_worker.sources import resolve_public,system_resolver


@dataclass
class Lease:
    password:str
    deadline:float
    remaining:int=8_000_000
    connections:int=0
    writers:list=field(default_factory=list)


class Proxy:
    def __init__(self,key):
        if len(key)<24:raise ValueError('render_proxy_key_required')
        self.key=key;self.leases={}

    def close_lease(self,identifier):
        lease=self.leases.pop(identifier,None)
        if lease:
            for writer in lease.writers:writer.close()

    async def reply(self,writer,status,data):
        raw=json.dumps(data).encode()
        writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n'.encode()+raw)
        await writer.drain()

    async def handle(self,reader,writer):
        upstream=None
        try:
            headers=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),5)
            if len(headers)>16384:raise ValueError('headers_too_large')
            lines=headers.decode('latin1').split('\r\n')
            method,target,version=lines[0].split(' ')
            fields={}
            for line in lines[1:]:
                if line:
                    name,value=line.split(':',1)
                    if name.lower() in fields:raise ValueError('duplicate_header')
                    fields[name.lower()]=value.strip()
            for name,lease in list(self.leases.items()):
                if lease.deadline<=time.monotonic():self.close_lease(name)
            if method in ('POST','DELETE'):
                if not hmac.compare_digest(fields.get('authorization',''),'Bearer '+self.key):
                    await self.reply(writer,'401 Unauthorized',{'error':'unauthorized'});return
                if target=='/lease' and method=='POST':
                    if self.leases:
                        await self.reply(writer,'409 Conflict',{'error':'render_busy'});return
                    identifier=secrets.token_hex(16);password=secrets.token_hex(32)
                    self.leases[identifier]=Lease(password,time.monotonic()+26)
                    await self.reply(writer,'200 OK',{'lease':identifier,'password':password});return
                if target.startswith('/lease/') and method=='DELETE':
                    self.close_lease(target.rsplit('/',1)[1])
                    await self.reply(writer,'200 OK',{'closed':True});return
                await self.reply(writer,'404 Not Found',{'error':'not_found'});return
            if method!='CONNECT':
                await self.reply(writer,'403 Forbidden',{'error':'https_only'});return
            given=fields.get('proxy-authorization','')
            try:
                identifier,password=base64.b64decode(given.removeprefix('Basic '),validate=True).decode().split(':',1)
            except (ValueError,UnicodeError):
                identifier=password=''
            lease=self.leases.get(identifier)
            if (not lease or not hmac.compare_digest(password,lease.password) or lease.deadline<=time.monotonic()):
                writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="render"\r\nContent-Length: 0\r\n\r\n');await writer.drain();return
            parsed=urlsplit('https://'+target)
            if parsed.port!=443 or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError('invalid_connect_target')
            if lease.connections>=48 or lease.remaining<=0:raise ValueError('render_resource_limit')
            lease.connections+=1
            resolved=await asyncio.wait_for(asyncio.to_thread(resolve_public,'https://'+target,system_resolver,3),4)
            if any(ipaddress.ip_address(ip).is_multicast for ip in resolved.ips):raise ValueError('multicast_destination')
            # open_connection receives a checked literal IP, not a name that could rebind.
            remote_reader,upstream=await asyncio.wait_for(asyncio.open_connection(resolved.ips[0],443),5)
            lease.writers.extend([writer,upstream])
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');await writer.drain()
            async def pump(source,destination):
                while lease.deadline>time.monotonic() and lease.remaining>0:
                    chunk=await asyncio.wait_for(source.read(min(32768,lease.remaining)),max(.01,lease.deadline-time.monotonic()))
                    if not chunk:return
                    # Other tunnels can consume the allowance during the read await.
                    allowed=min(len(chunk),lease.remaining)
                    if allowed<=0:return
                    lease.remaining-=allowed
                    destination.write(chunk[:allowed]);await destination.drain()
            tasks=[asyncio.create_task(pump(reader,upstream)),asyncio.create_task(pump(remote_reader,writer))]
            try:
                done,pending=await asyncio.wait(tasks,timeout=max(.01,lease.deadline-time.monotonic()),return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled():task.exception()
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
        except Exception:
            # Fixed outcome only, never echo URL/headers/exception details.
            try:await self.reply(writer,'403 Forbidden',{'error':'public_render_destination_unavailable'})
            except Exception:pass
        finally:
            if upstream:upstream.close()
            writer.close()
            try:await writer.wait_closed()
            except Exception:pass


async def main():
    proxy=Proxy(os.environ.get('RENDER_PROXY_KEY',''))
    server=await asyncio.start_server(proxy.handle,'0.0.0.0',3128,limit=16384)
    async with server:await server.serve_forever()


if __name__=='__main__':asyncio.run(main())
