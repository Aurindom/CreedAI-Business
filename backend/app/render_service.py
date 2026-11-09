"""Authenticated, single-page Chromium renderer on internal-only Docker networks."""
import asyncio
import hmac
import ipaddress
import os
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI,Header,HTTPException
from pydantic import BaseModel,Field

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
busy=False


def valid_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):return False
    host=parsed.hostname.lower().rstrip('.')
    if host=='localhost' or host.endswith(('.local','.internal','.localhost','.lan','.home','.corp')):return False
    try:
        ip=ipaddress.ip_address(host)
        if not (ip.ipv4_mapped if hasattr(ip,'ipv4_mapped') and ip.ipv4_mapped else ip).is_global or ip.is_multicast:return False
    except ValueError:
        if host.isdigit() or host.startswith('0x'):return False
    return True


class RenderRequest(BaseModel):
    url:str=Field(min_length=10,max_length=2000)


@app.get('/health')
def health():return {'ready':True}


@app.post('/render')
async def render(body:RenderRequest,authorization:str|None=Header(default=None)):
    global busy
    key=os.environ.get('RENDER_API_KEY','')
    if len(key)<24 or not hmac.compare_digest(authorization or '','Bearer '+key):raise HTTPException(401,'Unauthorized')
    try:valid=valid_url(body.url)
    except ValueError:valid=False
    if not valid:raise HTTPException(422,'Only public HTTPS pages can be rendered')
    if busy:raise HTTPException(429,'Renderer is busy',headers={'Retry-After':'30'})
    busy=True;browser=None;lease=None;engine=None
    proxy=os.environ.get('RENDER_PROXY_URL','http://render-proxy:3128')
    headers={'Authorization':'Bearer '+os.environ.get('RENDER_PROXY_KEY','')}
    try:
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            r=await client.post(proxy+'/lease',headers=headers);r.raise_for_status();lease=r.json()
        from playwright.async_api import async_playwright
        async with asyncio.timeout(20):
            engine=await async_playwright().start()
            browser=await engine.chromium.launch(headless=True,chromium_sandbox=True,
                proxy={'server':proxy,'username':lease['lease'],'password':lease['password']},
                args=['--proxy-bypass-list=<-loopback>','--disable-background-networking','--disable-quic',
                      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--renderer-process-limit=2'])
            context=await browser.new_context(service_workers='block',accept_downloads=False,
                viewport={'width':1365,'height':900},locale='en-US')
            requests=0;allowed_requests=0
            async def route(request_route):
                nonlocal requests,allowed_requests
                requests+=1;request=request_route.request
                try:allowed=valid_url(request.url)
                except ValueError:allowed=False
                if not allowed or requests>64 or request.resource_type in ('image','media','font'):
                    await request_route.abort()
                else:
                    allowed_requests+=1
                    await request_route.continue_()
            await context.route('**/*',route)
            page=await context.new_page()
            await page.goto(body.url,wait_until='domcontentloaded',timeout=14000)
            await page.wait_for_timeout(1200)
            # One explicit monthly billing control, never a signup/purchase action.
            import re
            for role in ('tab','radio','button'):
                monthly=page.get_by_role(role,name=re.compile(r'^monthly(?: billing)?$',re.I))
                if await monthly.count()==1 and await monthly.is_visible():
                    await monthly.click(timeout=1500,no_wait_after=True)
                    await page.wait_for_timeout(400)
                    break
            # Scroll boundedly to trigger lazy pricing sections; no login/captcha bypass.
            await page.evaluate('window.scrollTo(0, Math.min(document.body.scrollHeight,6000))')
            await page.wait_for_timeout(400)
            # Remove hidden elements so annual/monthly toggle values cannot be mixed.
            html=await page.evaluate('''() => {
                const clone=document.documentElement.cloneNode(true);
                const original=[document.documentElement,...document.documentElement.querySelectorAll('*')];
                const copied=[clone,...clone.querySelectorAll('*')];
                original.forEach((el,i)=>{ const s=getComputedStyle(el); if(copied[i] && (s.display==='none'||s.visibility==='hidden'))copied[i].setAttribute('hidden',''); });
                clone.querySelectorAll('script,style,noscript,template,video,audio,iframe').forEach(el=>el.remove());
                return clone.outerHTML;
            }''')
            if len(html)>750000:raise ValueError('render_document_too_large')
            if not valid_url(page.url):raise ValueError('invalid_final_url')
            return {'version':1,'url':page.url,'html':html,'requests':requests,'allowed_requests':allowed_requests,'mode':'rendered'}
    except HTTPException:raise
    except Exception:
        raise HTTPException(503,'Rendered evidence is unavailable; retain pending verification') from None
    finally:
        try:
            if browser:await asyncio.wait_for(browser.close(),3)
        except Exception:pass
        try:
            if engine:await asyncio.wait_for(engine.stop(),2)
        except Exception:pass
        if lease:
            try:
                async with httpx.AsyncClient(timeout=3,trust_env=False) as client:
                    await client.delete(proxy+'/lease/'+lease['lease'],headers=headers)
            except Exception:pass
        busy=False
