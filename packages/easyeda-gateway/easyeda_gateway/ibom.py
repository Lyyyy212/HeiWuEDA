"""Self-contained assembly BOM export adapted from EasyEDA's Interactive HTML BOM extension."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .errors import ContractError
from .intelligence import build_pcb_report


IBOM_SCHEMA_VERSION = "easyeda.gateway.ibom-model.v1"


def build_ibom_model(snapshot: Mapping[str, Any], *, project: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if snapshot.get("schemaVersion") != "easyeda.gateway.pcb-snapshot.v1":
        raise ContractError("iBOM export requires an easyeda.gateway.pcb-snapshot.v1 payload")
    components = [dict(item) for item in snapshot.get("components", []) if isinstance(item, Mapping)]
    pads = [dict(item) for item in snapshot.get("pads", []) if isinstance(item, Mapping)]
    lines = [dict(item) for item in snapshot.get("lines", []) if isinstance(item, Mapping)]
    arcs = [dict(item) for item in snapshot.get("arcs", []) if isinstance(item, Mapping)]
    vias = [dict(item) for item in snapshot.get("vias", []) if isinstance(item, Mapping)]
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for component in components:
        if component.get("addIntoBom") is False:
            continue
        procurement = dict(component.get("procurement") or {})
        other = dict(component.get("otherProperty") or {})
        designator = str(component.get("designator") or component.get("primitiveId") or "")
        value = str(component.get("name") or other.get("Value") or other.get("Comment") or "")
        footprint = component.get("footprint")
        if isinstance(footprint, Mapping):
            footprint_name = str(footprint.get("name") or footprint.get("uuid") or "")
        else:
            footprint_name = str(other.get("Footprint") or footprint or "")
        side = "front" if _int(component.get("layer")) == 1 else "back" if _int(component.get("layer")) == 2 else "other"
        key = (
            value,
            footprint_name,
            str(procurement.get("manufacturer") or ""),
            str(procurement.get("manufacturerPart") or ""),
            str(procurement.get("supplier") or ""),
            str(procurement.get("supplierPart") or ""),
            side,
        )
        entry = grouped.setdefault(
            key,
            {
                "value": value,
                "footprint": footprint_name,
                "manufacturer": key[2],
                "manufacturerPart": key[3],
                "supplier": key[4],
                "supplierPart": key[5],
                "side": side,
                "designators": [],
            },
        )
        entry["designators"].append(designator)
    bom = []
    for entry in grouped.values():
        entry["designators"].sort(key=_natural_key)
        entry["quantity"] = len(entry["designators"])
        bom.append(entry)
    bom.sort(key=lambda item: _natural_key(item["designators"][0] if item["designators"] else ""))
    report = build_pcb_report(snapshot)
    project_value = dict(project or {})
    title = str(project_value.get("friendlyName") or project_value.get("name") or "EasyEDA PCB")
    if "\ufffd" in title:
        title = "EasyEDA PCB"
    return {
        "schemaVersion": IBOM_SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "title": title,
            "projectUuid": project_value.get("uuid"),
            "documentUuid": project_value.get("documentUuid"),
            "profile": "assembly-lite.v1",
            "source": "easyeda/eext-interactive-html-bom",
        },
        "statistics": {**report["statistics"], "bomGroups": len(bom)},
        "boardBounds": report["boardBounds"],
        "bom": bom,
        "components": components,
        "pads": pads,
        "lines": lines,
        "arcs": arcs,
        "vias": vias,
        "nets": [str(item.get("net") or "") for item in snapshot.get("netLengths", []) if isinstance(item, Mapping)],
    }


def render_ibom_html(model: Mapping[str, Any]) -> str:
    if model.get("schemaVersion") != IBOM_SCHEMA_VERSION:
        raise ContractError(f"iBOM renderer requires {IBOM_SCHEMA_VERSION}")
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return _HTML_TEMPLATE.replace("__IBOM_DATA__", payload)


def write_ibom_html(path: str | Path, model: Mapping[str, Any]) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(render_ibom_html(model), encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _natural_key(value: str) -> tuple[Any, ...]:
    import re

    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EasyEDA Interactive BOM</title>
<style>
:root{color-scheme:light dark;--bg:#f5f7fa;--card:#fff;--text:#172033;--muted:#657089;--line:#d9e0ea;--accent:#2563eb;--front:#ef4444;--back:#2563eb}*{box-sizing:border-box}body{margin:0;font:14px system-ui,"Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text)}header{padding:16px 20px;background:#111827;color:#fff;display:flex;gap:20px;align-items:center;justify-content:space-between}header h1{font-size:18px;margin:0}header small{color:#b8c1d1}.toolbar{padding:12px 20px;display:flex;gap:10px;flex-wrap:wrap}.toolbar input,.toolbar select{padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--text)}main{display:grid;grid-template-columns:minmax(360px,1fr) minmax(420px,1.2fr);gap:14px;padding:0 20px 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}.stats{display:flex;gap:16px;padding:12px 16px;color:var(--muted);border-bottom:1px solid var(--line)}.board{height:620px;width:100%;background:#101827}.board text{font-size:10px;fill:#fff;pointer-events:none}.board .outline{stroke:#f8fafc;fill:none}.board .track-front{stroke:var(--front)}.board .track-back{stroke:var(--back)}.board .component{fill:#f59e0b;stroke:#fff;cursor:pointer}.board .component.back{fill:#3b82f6}.board .hidden{display:none}.table-wrap{max-height:620px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{position:sticky;top:0;background:var(--card);z-index:2}tr:hover,tr.active{background:rgba(37,99,235,.12)}td.refs{white-space:normal;min-width:120px}.done{opacity:.48;text-decoration:line-through}@media(max-width:980px){main{grid-template-columns:1fr}.board{height:460px}}@media(prefers-color-scheme:dark){:root{--bg:#0b1120;--card:#151d2e;--text:#e5e7eb;--muted:#9ba6ba;--line:#2b3549}}
</style>
</head>
<body>
<header><div><h1 id="title">Interactive BOM</h1><small id="meta"></small></div><small>黑五EDA · assembly-lite.v1</small></header>
<div class="toolbar"><input id="search" placeholder="搜索位号、型号、封装"><select id="side"><option value="all">全部面</option><option value="front">正面</option><option value="back">背面</option></select><select id="tracks"><option value="all">全部走线</option><option value="front">仅顶层</option><option value="back">仅底层</option><option value="none">隐藏走线</option></select></div>
<main><section class="card"><div class="stats" id="stats"></div><div class="table-wrap"><table><thead><tr><th>完成</th><th>位号</th><th>数量</th><th>值</th><th>封装</th><th>制造商料号</th><th>立创编号</th><th>面</th></tr></thead><tbody id="bom"></tbody></table></div></section><section class="card"><svg class="board" id="board" role="img" aria-label="PCB assembly preview"></svg></section></main>
<script type="application/json" id="ibom-data">__IBOM_DATA__</script>
<script>
const data=JSON.parse(document.getElementById('ibom-data').textContent);const NS='http://www.w3.org/2000/svg';const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));$('#title').textContent=data.metadata.title;$('#meta').textContent=`${data.metadata.projectUuid||''} · ${data.generatedAt}`;$('#stats').innerHTML=`<span>元件 ${data.statistics.components}</span><span>焊盘 ${data.statistics.pads}</span><span>过孔 ${data.statistics.vias}</span><span>网络 ${data.statistics.nets}</span><span>BOM组 ${data.statistics.bomGroups}</span>`;
function svg(tag,attrs){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n}const board=$('#board'),b=data.boardBounds,pad=20,w=Math.max(1,b.maxX-b.minX),h=Math.max(1,b.maxY-b.minY);board.setAttribute('viewBox',`${b.minX-pad} ${b.minY-pad} ${w+pad*2} ${h+pad*2}`);for(const l of data.lines){const cls=Number(l.layer)===11?'outline':Number(l.layer)===1?'track-front':Number(l.layer)===2?'track-back':'';if(!cls)continue;board.append(svg('line',{x1:l.startX,y1:l.startY,x2:l.endX,y2:l.endY,'stroke-width':Math.max(2,Number(l.lineWidth)||2),class:cls,'data-layer':Number(l.layer)===1?'front':Number(l.layer)===2?'back':'outline'}))}for(const a of data.arcs){if(Number(a.layer)!==11)continue;board.append(svg('line',{x1:a.startX,y1:a.startY,x2:a.endX,y2:a.endY,'stroke-width':Math.max(2,Number(a.lineWidth)||2),class:'outline'}))}for(const c of data.components){const side=Number(c.layer)===1?'front':Number(c.layer)===2?'back':'other',g=svg('g',{'data-ref':c.designator||'', 'data-side':side});const dot=svg('circle',{cx:c.x,cy:c.y,r:12,class:`component ${side==='back'?'back':''}`});const label=svg('text',{x:Number(c.x)+15,y:Number(c.y)-10});label.textContent=c.designator||'';g.append(dot,label);board.append(g)}
function render(){const q=$('#search').value.trim().toLowerCase(),side=$('#side').value,tb=$('#bom');tb.innerHTML='';for(const [i,row] of data.bom.entries()){const hay=[row.designators.join(','),row.value,row.footprint,row.manufacturerPart,row.supplierPart].join(' ').toLowerCase();if(q&&!hay.includes(q)||side!=='all'&&row.side!==side)continue;const tr=document.createElement('tr');tr.dataset.refs=row.designators.join(',');tr.innerHTML=`<td><input type="checkbox" aria-label="完成"></td><td class="refs"></td><td>${row.quantity}</td><td>${esc(row.value)}</td><td>${esc(row.footprint)}</td><td>${esc(row.manufacturerPart)}</td><td>${esc(row.supplierPart)}</td><td>${row.side}</td>`;tr.querySelector('.refs').textContent=row.designators.join(', ');tr.querySelector('input').onchange=e=>tr.classList.toggle('done',e.target.checked);tr.onclick=e=>{if(e.target.tagName==='INPUT')return;document.querySelectorAll('[data-ref]').forEach(n=>n.classList.toggle('hidden',!row.designators.includes(n.dataset.ref)));document.querySelectorAll('#bom tr').forEach(n=>n.classList.remove('active'));tr.classList.add('active')};tb.append(tr)}}render();$('#search').oninput=render;$('#side').onchange=render;$('#tracks').onchange=e=>document.querySelectorAll('[data-layer]').forEach(n=>n.classList.toggle('hidden',e.target.value==='none'||e.target.value!=='all'&&n.dataset.layer!==e.target.value));board.ondblclick=()=>document.querySelectorAll('[data-ref]').forEach(n=>n.classList.remove('hidden'));
</script>
</body>
</html>
"""
