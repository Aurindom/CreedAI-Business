"""Structural price evidence. Never splice a cheap tier into another tier's features."""
import hashlib
import math
import re
from html.parser import HTMLParser

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


class Node:
    def __init__(self,tag,attrs=()):
        self.tag=tag;self.attrs=dict(attrs);self.children=[]
    def hidden(self):
        return self.tag in ('script','style','noscript','template','nav','footer','aside','menu','blockquote') or 'hidden' in self.attrs or 'inert' in self.attrs or self.attrs.get('aria-hidden')=='true' or bool(re.search(r'display\s*:\s*none|visibility\s*:\s*hidden|(?:^|;)\s*opacity\s*:\s*0(?:[;\s]|$)',self.attrs.get('style') or '',re.I))
    def text(self):
        if self.hidden():
            return ''
        text=' '.join(c.text() if isinstance(c,Node) else c for c in self.children)
        if not text.strip():
            text=self.attrs.get('aria-label') or self.attrs.get('alt') or ''
        return ' '.join(text.split())
    def nodes(self,tags):
        if self.hidden():return []
        out=[]
        for child in self.children:
            if isinstance(child,Node):
                if child.tag in tags and not child.hidden():out.append(child)
                out.extend(child.nodes(tags))
        return out


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.root=Node('root');self.stack=[self.root];self.count=0
    def handle_starttag(self,tag,attrs):
        self.count+=1
        if self.count>15000:return
        node=Node(tag,attrs);self.stack[-1].children.append(node)
        if tag not in VOID and len(self.stack)<100:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:];break
    def handle_data(self,data):
        if self.count<=15000:self.stack[-1].children.append(data[:20000])


def blocks_from_html(html,url):
    parser=Parser();parser.feed(html[:750000]);parser.close();blocks=[]
    visible=parser.root.text()
    currency=re.search(r'\ball prices(?: shown)? (?:are )?in (?:USD|US dollars)\b',visible,re.I)
    selected=[]
    for control in parser.root.nodes({'button','input','div','label'}):
        if control.attrs.get('aria-checked')=='true' or control.attrs.get('aria-selected')=='true' or 'checked' in control.attrs:
            label=control.text().strip()
            if re.match(r'^(?:(?:pay|bill|billed)\s+)?monthly\b',label,re.I):selected.append('monthly')
            elif re.match(r'^(?:(?:pay|bill|billed)\s+)?annually?\b',label,re.I):selected.append('annual')
    billing=next(iter(set(selected))) if len(set(selected))==1 else 'unselected' if re.search(r'\b(?:annually|annual|yearly)\b',visible,re.I) else None
    for node in parser.root.nodes({'article','section','div','li'}):
        marker=' '.join(str(node.attrs.get(k,'')) for k in ('class','id','data-testid'))
        if not re.search(r'pricing|price|plan|tier|package',marker,re.I):continue
        headings=[h.text() for h in node.nodes({'h2','h3','h4'}) if h.text()]
        if not headings:
            headings=list(dict.fromkeys(n.text() for n in node.nodes({'p','span','div','h5','h6'})
                if re.search(r'(?:plan|tier|pricing)[-_](?:name|title)(?:$|[-_\s])',str(n.attrs.get('class','')),re.I)
                and 0<len(n.text())<=100 and not re.search(r'[$\u20ac\u00a3]|\b(?:month|annually|yearly)\b',n.text(),re.I)))
        if len(headings)!=1:continue
        text=node.text()
        if 20<=len(text)<=2500 and re.search(r'USD|US\$|\$|\bfree\b',text,re.I):
            blocks.append({'name':headings[0][:100],'text':text,'url':url,'kind':'pricing_card'})
    for table in parser.root.nodes({'table'}):
        rows=[]
        for row in table.nodes({'tr'}):
            cells=[c.text() for c in row.children if isinstance(c,Node) and c.tag in ('th','td')]
            if cells:rows.append(cells)
        if len(rows)<2 or len(rows[0])<2 or len(rows[0])>12:continue
        headers=rows[0]
        for column in range(1,len(headers)):
            if not headers[column] or len(headers[column])>100:continue
            lines=[headers[column]]
            for row in rows[1:]:
                if len(row)==len(headers):lines.append(row[0]+': '+row[column])
            text='\n'.join(lines)
            if len(text)<=3500:blocks.append({'name':headers[column],'text':text,'url':url,'kind':'pricing_column'})
    seen=set();result=[]
    for block in blocks:
        block.update(currency='USD' if currency else None,currency_quote=currency.group() if currency else None,billing_selection=billing)
        digest=hashlib.sha256((url+'\n'+block['text']).encode()).hexdigest()
        if digest not in seen:
            block['id']=digest;result.append(block);seen.add(digest)
    result=result[:40]
    # A comparison column may omit its price. Join only to an unambiguous price
    # card for the exact same named plan on the same official document.
    name_key=lambda value:re.sub(r'\s+(?:plan|tier)$','',' '.join(value.lower().split()))
    cards={}
    for block in result:
        if block['kind']=='pricing_card' and (price:=price_from_block(block)) is not None:
            cards.setdefault(name_key(block['name']),[]).append((block,price))
    joins=[]
    for block in result:
        if block['kind']!='pricing_column' or price_from_block(block) is not None:continue
        matches=cards.get(name_key(block['name']),[])
        if not matches or len({price for _,price in matches})!=1:continue
        card,price=min(matches,key=lambda item:len(item[0]['text']))
        joined={**block,'kind':'pricing_plan_join','price_block_id':card['id'],'price_text':card['text'],
                'text':card['text']+'\n'+block['text'],'feature_text':block['text'],'joined_price':price}
        joined['id']=hashlib.sha256((card['id']+block['id']).encode()).hexdigest()
        joins.append(joined)
    return result+joins[:40]


def price_from_block(block):
    text=block['text']
    if block.get('billing_selection') in ('annual','unselected'):return None
    if re.search(r'\b(annually|annual|yearly|per year|per user|per seat|per location|per contact|per email|per minute|per call|per conversation|per credit|per message|per transaction|per request|per token|overage|usage.based|starting at|from just|setup fee|required add.on|trial pric\w*|introductory|promo)\b',text,re.I):return None
    prices=re.findall(r'(?:\bUSD\s*\$?|US\$\s*)((?:[1-9]\d{0,2}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?![\d.,])',text,re.I)
    if not prices and block.get('currency')=='USD' and block.get('currency_quote'):
        prices=re.findall(r'\$\s*((?:[1-9]\d{0,2}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?![\d.,])',text)
    if len(set(prices))==1 and re.search(r'\b(month|monthly|mo)\b',text,re.I):
        amount=float(prices[0].replace(',',''))
        if not math.isfinite(amount):return None
    elif not prices and (re.fullmatch(r'free(?: plan| tier)?',block['name'].strip(),re.I)
                         or re.search(r'\b(?:price|cost):\s*(?:free|USD\s*0)\b|\bfree (?:plan|tier)\b',text,re.I)):
        amount=0.0
    else:return None
    if amount==0 and re.search(r'\btrial\b',text,re.I):return None
    monetary=re.findall(r'(?:USD\s*\$?|US\$|\$|\u20ac|\u00a3)\s*((?:[1-9]\d{0,2}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?![\d.,])',text,re.I)
    if any(float(value.replace(',',''))!=amount for value in monetary):return None
    return amount


def qualified_plan(block,phrases):
    from .discovery_worker.extract import phrase_regex,scan_phrase
    text=block.get('feature_text',block['text'])
    supported=any(scan_phrase(text.casefold(),phrase_regex(phrase))[0] for phrase in phrases)
    if not supported:return None
    if block.get('kind') in ('pricing_column','pricing_plan_join'):
        # A row label is not inclusion. Empty cells and ambiguous icons stay unconfirmed.
        feature_rows=[line for line in text.splitlines() if any(scan_phrase(line.casefold(),phrase_regex(phrase))[0] for phrase in phrases)]
        if not any(re.search(r':\s*(?:yes|included|available|supported|\u2713|\u2714)\s*$',line,re.I) for line in feature_rows):return None
    amount=price_from_block({**block,'text':block.get('price_text',block['text'])})
    if amount is None:return None
    # A table cell explicitly marked absent cannot become an included feature.
    for line in text.splitlines():
        if any(phrase_regex(phrase).search(line.casefold()) for phrase in phrases) and re.search(r':\s*(?:no|not included|unavailable|excluded|[-–—✗✕×])\s*$',line,re.I):return None
    return {'name':block['name'],'price_usd_monthly':amount,'billing':'flat_monthly','included':True,'url':block['url'],
            'quote':block['text'][:3500],'block_id':block['id'],'price_block_id':block.get('price_block_id'),
            'currency_quote':block.get('currency_quote'),'basis':'named_plan_join' if block.get('price_block_id') else 'same_pricing_block'}
