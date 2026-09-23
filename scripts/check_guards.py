"""Local-browser freshness/execution regressions. No model calls or external websites."""

from urllib.parse import quote

from jev_ultrafast.browser import Browser, StalePage

HTML = """<!doctype html><title>Guard checks</title>
<style>body{margin:30px}button{width:180px;height:50px}#outside{position:absolute;top:3000px}</style>
<p id="context">Cart total: $10</p>
<button id="target" onclick="window.clicks=(window.clicks||0)+1">Continue</button>
<label>City<input id="field" value="Zurich"></label>
<label><input id="toggle" type="checkbox">Refundable</label>
<select aria-label="Category"><option>All</option><option>Design</option></select>
<p id="outside">Unrelated offscreen text</p>"""


def main():
    browser = Browser("data:text/html," + quote(HTML))
    passed = []
    try:
        page = browser.observe(screenshot=False)
        action = next(a for a in page["actions"] if a["label"] == "Continue")
        browser.evaluate("document.querySelector('#target').style.transform='translateX(200px)'")
        assert browser.fresh(page), "Movement should use fresh geometry, not another model call"
        browser.act(action, page)
        assert browser.evaluate("window.clicks") == 1
        passed.append("moving target clicked at its current location")

        browser.evaluate("document.querySelector('#outside').textContent='Updated outside the viewport'")
        assert browser.fresh(page)
        passed.append("unrelated offscreen text does not invalidate")

        mutations = {
            "visible context": "document.querySelector('#context').textContent='Cart total: $100'",
            "accessible label": "document.querySelector('#target').setAttribute('aria-label','Delete account')",
            "field property": "document.querySelector('#field').value='London'",
            "checkbox property": "document.querySelector('#toggle').checked=true",
            "disabled target": "document.querySelector('#target').disabled=true",
            "read-only field": "document.querySelector('#field').readOnly=true",
            "hidden target": "document.querySelector('#target').style.display='none'",
            "replaced node": "document.querySelector('#target').outerHTML=document.querySelector('#target').outerHTML",
            "dropdown option": "document.querySelector('select').options[1].text='Coastal'",
        }
        for label, expression in mutations.items():
            browser.evaluate("document.querySelector('#target').style.display='block'; "
                             "document.querySelector('#target').disabled=false")
            page = browser.observe(screenshot=False)
            browser.evaluate(expression)
            assert not browser.fresh(page), label
            passed.append(label + " invalidates")

        browser.evaluate("document.querySelector('#target').disabled=false; "
                         "document.querySelector('#target').style.display='block'")
        page = browser.observe(screenshot=False)
        action = next(a for a in page["actions"] if a["label"] == "Delete account")
        # A textless overlay does not alter the model's semantic state, but must block a click.
        browser.evaluate("const cover=document.createElement('div'); "
                         "cover.style.cssText='position:fixed;inset:0;z-index:9999;background:white'; "
                         "document.body.append(cover)")
        assert browser.fresh(page)
        try:
            browser.act(action, page)
        except (RuntimeError, StalePage):
            pass
        else:
            raise AssertionError("Covered target was clicked")
        assert browser.evaluate("window.clicks") == 1
        passed.append("overlay blocked before input")

        browser.evaluate("document.body.innerHTML=" + repr("""
          <form><p id="price">Total $10</p>
          <button type="button" id="buy">Buy</button>
          <label>Search <input id="query" role="combobox" aria-controls="suggestions"></label>
          <div role="listbox" id="suggestions"></div>
          <label><input id="check" type="checkbox">Enabled</label>
          <label><input id="radio" type="radio">Choice</label>
          <input id="readonly" aria-label="Read only" readonly>
          <input id="secret" type="password" value="never expose this">
          <button id="off" disabled>Disabled</button>
          <select id="category" aria-label="Category">
            <option>All</option><option>Design</option><option disabled>Unavailable</option>
          </select></form><aside id="unrelated">News</aside>
        """))
        page = browser.observe(screenshot=False)
        buy = next(a for a in page["actions"] if a["label"] == "Buy")
        browser.evaluate("document.querySelector('#unrelated').textContent='New unrelated news'")
        assert browser.fresh(page, buy)
        assert not browser.fresh(page)
        passed.append("click guard accepts unrelated visible updates; terminal guard rejects them")
        for label, expression in {
            "nearby price": "document.querySelector('#price').textContent='Total $100'",
            "form value": "document.querySelector('#query').value='changed'",
            "form toggle": "document.querySelector('#check').checked=true",
            "target replacement": "document.querySelector('#buy').outerHTML=document.querySelector('#buy').outerHTML",
        }.items():
            page = browser.observe(screenshot=False)
            buy = next(a for a in page["actions"] if a["label"] == "Buy")
            browser.evaluate(expression)
            assert not browser.fresh(page, buy), label
            passed.append(label + " invalidates action-specific guard")

        page = browser.observe(screenshot=False)
        actions = page["actions"]
        for role in ("checkbox", "radio"):
            assert {a["kind"] for a in actions if a.get("role") == role} == {"click"}
        assert {a["kind"] for a in actions if a["label"] == "Read only"} == {"click"}
        assert not any(a["label"] == "Disabled" or a.get("value") == "never expose this" for a in actions)
        assert [a["value"] for a in actions if a["kind"] == "select"] == ["Design"]
        passed.append("native controls expose only supported operations and safe values")

        select = next(a for a in actions if a["kind"] == "select")
        browser.act(select, page)
        assert browser.evaluate("document.querySelector('#category').value") == "Design"
        passed.append("native dropdown selects an observed option")

        browser.evaluate("document.querySelector('#query').addEventListener('input',()=>setTimeout(()=>{"
                         "document.querySelector('#suggestions').innerHTML='<div role=option>Generated</div>'"
                         "},60))")
        page = browser.observe(screenshot=False)
        field = next(a for a in page["actions"] if a["kind"] == "fill")
        browser.act(field, page, text="Generated")
        page = browser.observe(screenshot=False)
        value = browser.evaluate("document.querySelector('#query').value")
        assert value == "Generated", repr(value)
        assert any(a.get("role") == "option" for a in page["actions"])
        passed.append("real text input waits for asynchronous combobox suggestions")

        # Site headers often live in an open shadow root (e.g. a <provider-header> web component).
        browser.evaluate("document.body.innerHTML='<div id=\"host\"></div>';"
                         "const root=document.querySelector('#host').attachShadow({mode:'open'});"
                         "root.innerHTML='<input aria-label=\"Shadow keyword\"><button>Shadow search</button>';"
                         "root.querySelector('button').onclick=()=>{window.shadowClicks=(window.shadowClicks||0)+1}")
        shadow_value = "document.querySelector('#host').shadowRoot.querySelector('input').value"
        page = browser.observe(screenshot=False)
        field = next((a for a in page["actions"] if a["kind"] == "fill" and a["label"] == "Shadow keyword"), None)
        assert field, "Shadow-root field was not observed"
        browser.act(field, page, text="Logo")
        page = browser.observe(screenshot=False)
        assert browser.evaluate(shadow_value) == "Logo"
        passed.append("open shadow-root field is observed and filled")
        button = next((a for a in page["actions"] if a["label"] == "Shadow search"), None)
        assert button, "Shadow-root button was not observed"
        browser.act(button, page)
        assert browser.evaluate("window.shadowClicks") == 1
        passed.append("open shadow-root button passes its own hit test")
        page = browser.observe(screenshot=False)
        button = next(a for a in page["actions"] if a["label"] == "Shadow search")
        browser.evaluate("const shadowCover=document.createElement('div'); "
                         "shadowCover.style.cssText='position:fixed;inset:0;z-index:9999;background:white'; "
                         "document.body.append(shadowCover)")
        try:
            browser.act(button, page)
        except (RuntimeError, StalePage):
            pass
        else:
            raise AssertionError("Covered shadow-root target was clicked")
        assert browser.evaluate("window.shadowClicks") == 1
        passed.append("document overlay blocks a shadow-root target")
        browser.evaluate("document.body.lastElementChild.remove()")
        page = browser.observe(screenshot=False)
        browser.evaluate(shadow_value + "='Other'")
        assert not browser.fresh(page)
        passed.append("shadow-root field value invalidates the page marker")

        # Nested component whose label is slotted light-DOM text, e.g. <app-button>Log in</app-button>.
        browser.evaluate("document.body.innerHTML='<div id=\"outer\"></div>';"
                         "customElements.get('x-btn')||customElements.define('x-btn',class extends HTMLElement{"
                         "constructor(){super();this.attachShadow({mode:'open'}).innerHTML="
                         "'<button style=\"width:180px;height:50px\"><slot></slot></button>';"
                         "this.shadowRoot.querySelector('button').onclick="
                         "()=>{window.nestedClicks=(window.nestedClicks||0)+1}}});"
                         "document.querySelector('#outer').attachShadow({mode:'open'}).innerHTML="
                         "'<x-btn>Nested go</x-btn>'")
        page = browser.observe(screenshot=False)
        nested = next((a for a in page["actions"] if a["label"] == "Nested go"), None)
        assert nested, "Slotted label of a nested shadow-root button was not observed"
        browser.act(nested, page)
        assert browser.evaluate("window.nestedClicks") == 1
        passed.append("nested shadow-root button is named from its slot and clicked")
        page = browser.observe(screenshot=False)
        nested = next(a for a in page["actions"] if a["label"] == "Nested go")
        browser.evaluate("document.body.append(Object.assign(document.createElement('div'),"
                         "{style:'position:fixed;inset:0;z-index:9999;background:white'}))")
        try:
            browser.act(nested, page)
        except (RuntimeError, StalePage):
            pass
        else:
            raise AssertionError("Covered nested shadow-root target was clicked")
        assert browser.evaluate("window.nestedClicks") == 1
        passed.append("document overlay blocks a nested shadow-root target")

        # A search box that submits only on Enter (no Search button), like Coconala's header.
        browser.evaluate("document.body.innerHTML='<input aria-label=\"Keyword\">"
                         "<textarea aria-label=\"Notes\">x</textarea>';"
                         "document.querySelector('input').addEventListener('keydown',"
                         "e=>{if(e.key==='Enter')window.submitted=e.target.value})")
        page = browser.observe(screenshot=False)
        assert not any(a["kind"] == "enter" for a in page["actions"]), "Empty field or textarea offered Enter"
        field = next(a for a in page["actions"] if a["kind"] == "fill" and a["label"] == "Keyword")
        browser.act(field, page, text="Logo")
        page = browser.observe(screenshot=False)
        enter = [a for a in page["actions"] if a["kind"] == "enter"]
        assert [a["label"] for a in enter] == ["Submit Keyword"], enter
        browser.act(enter[0], page)
        assert browser.evaluate("window.submitted") == "Logo"
        passed.append("Enter is offered only for a filled single-line field and submits it")
        browser.call("Page.navigate", url="about:blank")
        assert not browser.fresh(page, field)
        passed.append("navigation invalidates the old document")
    finally:
        browser.close()
    print("\n".join(passed))
    print(f"PASS: {len(passed)} browser guard checks; no model calls")


if __name__ == "__main__":
    main()
