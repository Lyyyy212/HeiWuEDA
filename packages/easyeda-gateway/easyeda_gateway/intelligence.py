"""Read-only design intelligence adapted from official EasyEDA extension algorithms."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping
import re

from .errors import ContractError


NETLIST_ANALYSIS_SCHEMA = "easyeda.gateway.netlist-analysis.v1"
SCHEMATIC_ANALYSIS_SCHEMA = "easyeda.gateway.schematic-analysis.v1"
PCB_REPORT_SCHEMA = "easyeda.gateway.pcb-design-report.v1"
FLOATING_NET = "(悬空)"


def analyze_netlist(netlist: Mapping[str, Any]) -> dict[str, Any]:
    """Build pin/net tables, connector mappings, topology data, and a grouped BOM."""
    components_value = netlist.get("components", netlist)
    if isinstance(components_value, Mapping):
        components = [(str(key), value) for key, value in components_value.items()]
    elif isinstance(components_value, list):
        components = [(str(index), value) for index, value in enumerate(components_value)]
    else:
        raise ContractError("EasyEDA netlist does not contain a components object or array")

    pin_rows: list[dict[str, Any]] = []
    normalized_components: list[dict[str, Any]] = []
    net_to_pins: dict[str, list[dict[str, str]]] = defaultdict(list)
    floating_count = 0
    unnamed_nets: set[str] = set()

    for component_id, raw_component in components:
        component = _mapping(raw_component)
        props = _mapping(component.get("props"))
        designator = str(props.get("Designator") or component.get("designator") or component_id)
        category = _component_category(designator)
        description = str(props.get("Description") or props.get("Device_name") or props.get("Value") or "")
        pins_value = component.get("pinInfoMap") or component.get("pins") or {}
        pins = _mapping(pins_value)
        normalized_pins: list[dict[str, str]] = []
        for pin_number, raw_pin in pins.items():
            pin = _mapping(raw_pin)
            net = _normalize_net(pin.get("net"))
            pin_name = str(pin.get("pinName") or pin.get("name") or "")
            row = {
                "designator": designator,
                "pinNumber": str(pin_number),
                "pinName": pin_name,
                "net": net,
                "category": category,
                "description": description,
            }
            pin_rows.append(row)
            normalized_pins.append({"number": str(pin_number), "name": pin_name, "net": net})
            if net == FLOATING_NET:
                floating_count += 1
            else:
                net_to_pins[net].append(
                    {"designator": designator, "pinNumber": str(pin_number), "pinName": pin_name},
                )
                if net.startswith("$"):
                    unnamed_nets.add(net)
        normalized_pins.sort(key=lambda item: _natural_key(item["number"]))
        normalized_components.append(
            {
                "componentId": component_id,
                "designator": designator,
                "category": category,
                "description": description,
                "props": props,
                "pins": normalized_pins,
            },
        )

    pin_rows.sort(key=lambda row: (_natural_key(row["designator"]), _natural_key(row["pinNumber"])))
    normalized_components.sort(key=lambda item: _natural_key(item["designator"]))
    connections = _build_connections(net_to_pins)
    connector_pairs = _build_connector_pairs(normalized_components)
    bom = _group_netlist_bom(normalized_components)
    topology = [
        {
            "net": net,
            "group": _net_group(net),
            "pins": sorted(pins, key=lambda item: (_natural_key(item["designator"]), _natural_key(item["pinNumber"]))),
        }
        for net, pins in sorted(net_to_pins.items(), key=lambda item: _natural_key(item[0]))
    ]
    return {
        "schemaVersion": NETLIST_ANALYSIS_SCHEMA,
        "statistics": {
            "components": len(normalized_components),
            "namedNets": sum(not net.startswith("$") for net in net_to_pins),
            "unnamedNets": len(unnamed_nets),
            "pinConnections": len(pin_rows) - floating_count,
            "floatingPins": floating_count,
            "connectorPairs": len(connector_pairs),
            "bomGroups": len(bom),
        },
        "components": normalized_components,
        "pinNets": pin_rows,
        "connections": connections,
        "connectorPairs": connector_pairs,
        "topology": topology,
        "bom": bom,
    }


def analyze_schematic_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Analyze a fixed schematic snapshot while preserving netlist-export failures."""
    if snapshot.get("schemaVersion") != "easyeda.gateway.schematic-snapshot.v1":
        raise ContractError("Schematic analysis requires an easyeda.gateway.schematic-snapshot.v1 payload")
    component_pins = _list_of_mappings(snapshot.get("componentPins"))
    pin_count = sum(len(item.get("pins") or []) for item in component_pins)
    netlist = snapshot.get("netlist")
    netlist_analysis = analyze_netlist(netlist) if isinstance(netlist, Mapping) else None
    statistics: dict[str, Any] = {
        "components": len(component_pins),
        "activePageComponents": len(component_pins),
        "pins": pin_count,
        "activePagePins": pin_count,
        "noConnectedPins": _int(snapshot.get("noConnectedPins")),
        "connectivityAvailable": netlist_analysis is not None,
    }
    if netlist_analysis is not None:
        statistics.update(netlist_analysis["statistics"])
        statistics["netlistComponents"] = netlist_analysis["statistics"]["components"]
        statistics["activePageComponents"] = len(component_pins)
        statistics["pins"] = pin_count
        statistics["activePagePins"] = pin_count
    limitations = []
    if netlist_analysis is None:
        limitations.append(
            "Official SCH_ManufactureData.getNetlistFile did not provide a valid JSON netlist; connectivity claims are unavailable.",
        )
    if snapshot.get("componentStatus") == "unavailable":
        limitations.append("Official SCH_PrimitiveComponent.getAll failed; component and pin counts are unavailable.")
    if snapshot.get("pinErrors"):
        limitations.append("One or more component pin reads failed; pin counts are incomplete.")
    return {
        "schemaVersion": SCHEMATIC_ANALYSIS_SCHEMA,
        "project": _mapping(snapshot.get("project")),
        "document": _mapping(snapshot.get("document")),
        "netlistStatus": str(snapshot.get("netlistStatus") or ("available" if netlist_analysis else "unavailable")),
        "netlistError": snapshot.get("netlistError"),
        "componentStatus": str(snapshot.get("componentStatus") or "available"),
        "componentError": snapshot.get("componentError"),
        "pinErrors": _list_of_mappings(snapshot.get("pinErrors")),
        "statistics": statistics,
        "componentPins": component_pins,
        "netlistAnalysis": netlist_analysis,
        "limitations": limitations,
    }


def build_pcb_report(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize PCB metrics captured by the trusted composite read template."""
    if snapshot.get("schemaVersion") != "easyeda.gateway.pcb-snapshot.v1":
        raise ContractError("PCB report requires an easyeda.gateway.pcb-snapshot.v1 payload")
    components = _list_of_mappings(snapshot.get("components"))
    pads = _list_of_mappings(snapshot.get("pads"))
    lines = _list_of_mappings(snapshot.get("lines"))
    arcs = _list_of_mappings(snapshot.get("arcs"))
    polylines = _list_of_mappings(snapshot.get("polylines"))
    vias = _list_of_mappings(snapshot.get("vias"))
    net_lengths = _list_of_mappings(snapshot.get("netLengths"))
    outline_points: list[tuple[float, float]] = []
    for line in lines:
        if _int(line.get("layer")) == 11:
            outline_points.extend(
                [(_float(line.get("startX")), _float(line.get("startY"))), (_float(line.get("endX")), _float(line.get("endY")))],
            )
    for arc in arcs:
        if _int(arc.get("layer")) == 11:
            outline_points.extend(
                [(_float(arc.get("startX")), _float(arc.get("startY"))), (_float(arc.get("endX")), _float(arc.get("endY")))],
            )
    for polyline in polylines:
        if _int(polyline.get("layer")) == 11:
            outline_points.extend(_polygon_points(polyline.get("polygon")))
    used_board_outline = bool(outline_points)
    if not outline_points:
        outline_points.extend((_float(item.get("x")), _float(item.get("y"))) for item in components + pads + vias)
    bbox = _bbox(outline_points)
    width_mil = bbox["maxX"] - bbox["minX"]
    height_mil = bbox["maxY"] - bbox["minY"]
    net_lengths = sorted(net_lengths, key=lambda item: (-_float(item.get("lengthMil")), _natural_key(str(item.get("net") or ""))))
    return {
        "schemaVersion": PCB_REPORT_SCHEMA,
        "statistics": {
            "components": len(components),
            "pads": len(pads),
            "vias": len(vias),
            "tracks": len(lines) + len(arcs) + len(polylines),
            "nets": len(net_lengths),
            "netClasses": len(_list_or_mapping_values(snapshot.get("netClasses"))),
            "differentialPairs": len(_list_or_mapping_values(snapshot.get("differentialPairs"))),
            "equalLengthGroups": len(_list_or_mapping_values(snapshot.get("equalLengthGroups"))),
            "padPairGroups": len(_list_or_mapping_values(snapshot.get("padPairGroups"))),
        },
        "boardBounds": {
            **bbox,
            "widthMil": width_mil,
            "heightMil": height_mil,
            "widthMm": round(width_mil * 0.0254, 4),
            "heightMm": round(height_mil * 0.0254, 4),
            "boundingAreaMm2": round(width_mil * height_mil * 0.0254 * 0.0254, 4),
            "approximate": True,
            "basis": "board-outline bounding box" if used_board_outline else "primitive bounding box",
        },
        "netLengths": [
            {
                "net": str(item.get("net") or ""),
                "lengthMil": round(_float(item.get("lengthMil")), 4),
                "lengthMm": round(_float(item.get("lengthMil")) * 0.0254, 4),
            }
            for item in net_lengths
        ],
        "netClasses": _list_or_mapping_values(snapshot.get("netClasses")),
        "differentialPairs": _list_or_mapping_values(snapshot.get("differentialPairs")),
        "equalLengthGroups": _list_or_mapping_values(snapshot.get("equalLengthGroups")),
        "padPairGroups": _list_or_mapping_values(snapshot.get("padPairGroups")),
    }


def _build_connections(net_to_pins: Mapping[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for net, pins in sorted(net_to_pins.items(), key=lambda item: (_group_order(_net_group(item[0])), _natural_key(item[0]))):
        group = _net_group(net)
        ordered = sorted(pins, key=lambda item: (_natural_key(item["designator"]), _natural_key(item["pinNumber"])))
        if group in {"power", "ground"}:
            for target in ordered:
                rows.append({"group": group, "net": net, "source": {"designator": net, "pinNumber": "", "pinName": ""}, "target": target, "endpointCount": len(ordered)})
        elif len(ordered) == 2:
            rows.append({"group": group, "net": net, "source": ordered[0], "target": ordered[1], "endpointCount": 2})
        else:
            for endpoint in ordered:
                rows.append({"group": group, "net": net, "source": endpoint, "target": None, "endpointCount": len(ordered)})
    return rows


def _build_connector_pairs(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    connectors = [component for component in components if component["category"] == "connector"]
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(connectors):
        left_nets = {pin["net"]: pin for pin in left["pins"] if pin["net"] != FLOATING_NET}
        for right in connectors[index + 1 :]:
            right_nets = {pin["net"]: pin for pin in right["pins"] if pin["net"] != FLOATING_NET}
            common = sorted(set(left_nets) & set(right_nets), key=_natural_key)
            if not common:
                continue
            pairs.append(
                {
                    "left": left["designator"],
                    "right": right["designator"],
                    "mapping": [
                        {
                            "net": net,
                            "leftPin": left_nets[net]["number"],
                            "leftPinName": left_nets[net]["name"],
                            "rightPin": right_nets[net]["number"],
                            "rightPinName": right_nets[net]["name"],
                            "netType": _net_group(net),
                        }
                        for net in common
                    ],
                },
            )
    return pairs


def _group_netlist_bom(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for component in components:
        props = component["props"]
        key = tuple(
            str(props.get(field) or "")
            for field in ("Device_name", "Value", "Footprint", "Manufacturer", "Manufacturer Part", "Supplier Part")
        )
        entry = groups.setdefault(
            key,
            {
                "name": key[0],
                "value": key[1],
                "footprint": key[2],
                "manufacturer": key[3],
                "manufacturerPart": key[4],
                "supplierPart": key[5],
                "designators": [],
            },
        )
        entry["designators"].append(component["designator"])
    result = []
    for entry in groups.values():
        entry["designators"].sort(key=_natural_key)
        entry["quantity"] = len(entry["designators"])
        result.append(entry)
    result.sort(key=lambda item: _natural_key(item["designators"][0] if item["designators"] else ""))
    return result


def _component_category(designator: str) -> str:
    prefix = re.sub(r"\d+$", "", designator).upper()
    return {
        "U": "ic",
        "Q": "ic",
        "R": "resistor",
        "C": "capacitor",
        "L": "inductor",
        "D": "diode",
        "Y": "crystal",
        "X": "connector",
        "J": "connector",
        "CN": "connector",
        "P": "connector",
        "USB": "connector",
        "F": "fuse",
        "FB": "ferrite-bead",
        "TP": "test-point",
    }.get(prefix, "other")


def _net_group(net: str) -> str:
    upper = net.upper()
    if re.search(r"(^|[_+-])(GND|AGND|DGND|PGND|VSS)([_+-]|$)", upper):
        return "ground"
    if re.search(r"(^|[_+-])(VCC|VDD|VBAT|VIN|VOUT|[0-9.]+V)([_+-]|$)", upper):
        return "power"
    if any(token in upper for token in ("USB", "ETH", "HDMI")):
        return "interface"
    if any(token in upper for token in ("CLK", "OSC", "RESET")):
        return "clock-reset"
    return "other"


def _group_order(group: str) -> int:
    return {"interface": 0, "power": 1, "ground": 1, "clock-reset": 2, "other": 3}.get(group, 4)


def _normalize_net(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else FLOATING_NET


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value]


def _list_or_mapping_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return list(value.values())
    return []


def _polygon_points(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    if value and isinstance(value[0], list):
        result: list[tuple[float, float]] = []
        for child in value:
            result.extend(_polygon_points(child))
        return result
    result = []
    index = 0
    while index + 1 < len(value):
        if isinstance(value[index], (int, float)) and isinstance(value[index + 1], (int, float)):
            result.append((float(value[index]), float(value[index + 1])))
            index += 2
        else:
            index += 1
    return result


def _bbox(points: list[tuple[float, float]]) -> dict[str, float]:
    if not points:
        return {"minX": 0.0, "minY": 0.0, "maxX": 0.0, "maxY": 0.0}
    return {
        "minX": min(point[0] for point in points),
        "minY": min(point[1] for point in points),
        "maxX": max(point[0] for point in points),
        "maxY": max(point[1] for point in points),
    }


def _natural_key(value: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
