"""Smoke regression for archived-chat bottom navigation and refresh icon spacing."""
from pathlib import Path
from lxml import etree

root = Path(__file__).resolve().parents[1]
xml_path = root / 'static/src/xml/sale_ai_chat.xml'
css_path = root / 'static/src/scss/sale_ai_chat.scss'
manifest_path = root / '__manifest__.py'
xml = etree.parse(str(xml_path))
css = css_path.read_text()

footer = xml.xpath("//footer[@class='sale-ai-footer']")
assert len(footer) == 1
footer = footer[0]
archived = footer.xpath("./t[@t-elif=\"state.mode === 'chat' and state.viewingHistory\"]")
assert len(archived) == 1, 'Archived chat footer branch missing'
buttons = archived[0].xpath('./button')
assert len(buttons) == 1 and buttons[0].get('t-on-click') == 'returnToActive'
assert 'sale-ai-footer-return' in buttons[0].get('class').split()
assert 'Volver a conversación' in ''.join(buttons[0].itertext())
assert buttons[0].get('t-att-disabled') == 'state.busy || state.sending'

history = footer.xpath("./t[@t-elif=\"state.mode === 'history'\"]")
assert len(history) == 1 and history[0].xpath('./button')[0].get('t-on-click') == 'returnToActive'
mobile_preview = footer.xpath('./t[@t-else]')
assert len(mobile_preview) == 1 and mobile_preview[0].xpath('./button')[0].get('t-on-click') == 'showChat'

archive_heading = xml.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' sale-ai-readonly-heading ')]")
assert len(archive_heading) == 1
assert archive_heading[0].xpath('./strong[@class="sale-ai-archive-title"]')
assert 'display: flex; flex-direction: column; align-items: flex-start; gap: 6px' in css
assert '.sale-ai-load-quote-btn .fa { margin-right: 1px; }' in css
assert '.sale-ai-footer-return {' in css and '&:focus-visible' in css
assert '"version": "18.0.0.11.' in manifest_path.read_text()
print('OK: 11.22 archived chat footer, history return, heading spacing and refresh icon')
