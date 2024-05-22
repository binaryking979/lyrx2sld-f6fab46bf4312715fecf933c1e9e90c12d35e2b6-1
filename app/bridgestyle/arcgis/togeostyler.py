import base64
import math
import os
import tempfile
import uuid
from typing import Union
import json  # Import the JSON module

from .constants import ESRI_SYMBOLS_FONT, POLYGON_FILL_RESIZE_FACTOR, OFFSET_FACTOR, pt_to_px
from .expressions import convertExpression, convertWhereClause, processRotationExpression
from .wkt_geometries import to_wkt

_usedIcons = []
_warnings = []


def convert(arcgis, options=None):
    global _usedIcons
    _usedIcons = []
    global _warnings
    _warnings = []
    geostyler = processLayer(arcgis, options)
    return geostyler, _usedIcons, _warnings


def processLayer(layer, options=None):
    options = options or {}
    geostyler = {}
    
    try:
        if isinstance(layer, dict):
            geostyler["name"] = layer.get("name", "")  # Safely retrieve the "name" value from the layer
            
            if layer.get("type") == "CIMFeatureLayer":
                renderer = layer.get("renderer", {})
                rules = []
                
                if renderer.get("type") == "CIMSimpleRenderer":
                    rules.append(processSimpleRenderer(renderer, options))
                elif renderer.get("type") == "CIMUniqueValueRenderer":
                    if "groups" in renderer:
                        for group in renderer.get("groups", []):
                            rules.extend(processUniqueValueGroup(renderer.get("fields", []), group, options))
                    else:
                        if "defaultSymbol" in renderer:
                            rule = {
                                "name": "",
                                "symbolizers": processSymbolReference(renderer.get("defaultSymbol", {}), options),
                            }
                            rules.append(rule)
                elif renderer.get("type") == "CIMClassBreaksRenderer" and renderer.get("classBreakType") in ["GraduatedColor", "GraduatedSymbol"]:
                    rules.extend(processClassBreaksRenderer(renderer, options))
                else:
                    _warnings.append(f"Unsupported renderer type: {renderer.get('type', '')}")
            
                if layer.get("labelVisibility", False):
                    for labelClass in layer.get("labelClasses", []):
                        rules.append(processLabelClass(labelClass, options.get("tolowercase", False)))
                
                rotation = _getSymbolRotationFromVisualVariables(renderer, options.get("tolowercase", False))
                if rotation:
                    for rule in rules:
                        for symbolizer in rule.get("symbolizers", []):
                            symbolizer.update({"rotate": rotation})
                
                geostyler["rules"] = rules
            
            elif layer.get("type") == "CIMRasterLayer":
                _warnings.append('CIMRasterLayer is not supported yet.')
                
        else:
            _warnings.append("Input layer is not in the expected dictionary format.")
    
    except Exception as e:
        _warnings.append(f"Error processing layer: {str(e)}")
    
    return geostyler


# def processLayer(layer, options=None):
#     options = options or {}
#     tolowercase = options.get("tolowercase", False)
#     geostyler = {}
    
#     if isinstance(layer, dict):  # Check if layer is a dictionary
#         geostyler["name"] = layer.get("name", "")  # Use get() to safely access the "name" key
#     else:
#         _warnings.append("Invalid layer format. Expected dictionary, got %s" % type(layer))
#         return geostyler

#     # Rest of the function...



def processClassBreaksRenderer(renderer, options):
    rules = []
    symbolsAscending = []
    field = renderer["field"]
    lastbound = None
    tolowercase = options.get("tolowercase", False)
    rotation = _getSymbolRotationFromVisualVariables(renderer, tolowercase)
    for classbreak in renderer.get("breaks", []):
        symbolizers = processSymbolReference(classbreak["symbol"], options)
        upperbound = classbreak.get("upperBound", 0)
        if lastbound is not None:
            filt = [
                "And",
                [
                    "PropertyIsGreaterThan",
                    ["PropertyName", field.lower() if tolowercase else field],
                    lastbound,
                ],
                [
                    "PropertyIsLessThanOrEqualTo",
                    ["PropertyName", field.lower() if tolowercase else field],
                    upperbound,
                ],
            ]
        else:
            filt = [
                "PropertyIsLessThanOrEqualTo",
                ["PropertyName", field.lower() if tolowercase else field],
                upperbound,
            ]
        lastbound = upperbound
        if rotation:
            [symbolizer.update({"rotate": rotation}) for symbolizer in symbolizers]
        ruledef = {
            "name": classbreak.get("label", "classbreak"),
            "symbolizers": symbolizers,
            "filter": filt,
        }
        symbolsAscending.append(symbolizers)
        rules.append(ruledef)
    if not renderer.get('showInAscendingOrder', True):
        rules.reverse()
        for index, rule in enumerate(rules):
            rule["symbolizers"] = symbolsAscending[index]
    return rules


def processLabelClass(labelClass, tolowercase=False):
    textSymbol = labelClass["textSymbol"]["symbol"]
    expression = convertExpression(labelClass["expression"], labelClass["expressionEngine"], tolowercase)
    fontFamily = textSymbol.get("fontFamilyName", "Arial")
    fontSize = _ptToPxProp(textSymbol, 'height', 12, True)
    color = _extractFillColor(textSymbol["symbol"]["symbolLayers"])
    fontWeight = textSymbol.get("fontStyleName", "Regular")
    rotationProps = labelClass.get("maplexLabelPlacementProperties", {}).get(
        "rotationProperties", {}
    )
    rotationField = rotationProps.get("rotationField")
    symbolizer = {
        "kind": "Text",
        "anchor": "right",
        "rotate": 0,
        "color": color,
        "size": fontSize,
        "font": fontFamily,
        "weight": fontWeight,
        "offset": [0, 0],
    }
    if rotationField:
        symbolizer["rotate"] = _extractRotationAngle(rotationProps, rotationField)
    return {"name": expression, "symbolizers": [symbolizer]}


def processSimpleRenderer(renderer, options):
    return {
        "name": "",
        "symbolizers": processSymbolReference(renderer["symbol"], options),
    }


def processUniqueValueGroup(fields, group, options):
    rules = []
    defaultSymbol = group.get("defaultSymbol", {})
    for item in group.get("values", []):
        filter = _createUniqueValueFilter(fields, item)
        if filter is None:
            continue
        symbol = item.get("symbol", defaultSymbol)
        rule = {
            "name": "",
            "symbolizers": processSymbolReference(symbol, options),
            "filter": filter,
        }
        rules.append(rule)
    return rules


def processSymbolReference(symbol, options):
    symbolizers = []
    for reference in symbol["symbolLayers"]:
        kind = reference["type"]
        if kind == "CIMSolidFill":
            symbolizers.append(_processSolidFill(reference, options))
        elif kind == "CIMPictureFillSymbolLayer":
            symbolizers.append(_processPictureFill(reference, options))
        elif kind == "CIMVectorMarker":
            symbolizers.append(_processVectorMarker(reference, options))
        elif kind == "CIMPolygonSymbol":
            symbolizers.append(_processPolygonSymbol(reference, options))
        elif kind == "CIMSolidStroke":
            symbolizers.append(_processSolidStroke(reference, options))
        elif kind == "CIMHatchFillSymbolLayer":
            symbolizers.append(_processHatchFill(reference, options))
        elif kind == "CIMGradientFillSymbolLayer":
            symbolizers.append(_processGradientFill(reference, options))
        else:
            _warnings.append("Unsupported symbol type: %s" % str(kind))
    return symbolizers


def _processSolidFill(symbol, options):
    color = _extractFillColor(symbol)
    opacity = _extractOpacity(symbol)
    return {"kind": "Fill", "color": color, "opacity": opacity}


def _processPictureFill(symbol, options):
    _usedIcons.append(symbol["href"])
    return {"kind": "Icon", "src": symbol["href"], "opacity": 1}


def _processVectorMarker(symbol, options):
    _usedIcons.append(symbol["imageData"])
    color = _extractFillColor(symbol)
    opacity = _extractOpacity(symbol)
    return {"kind": "Mark", "wellKnownName": "circle", "fill": color, "opacity": opacity}


def _processPolygonSymbol(symbol, options):
    fill = None
    stroke = None
    for layer in symbol["symbolLayers"]:
        if layer["type"] == "CIMSolidFill":
            fill = _processSolidFill(layer, options)
        elif layer["type"] == "CIMSolidStroke":
            stroke = _processSolidStroke(layer, options)
    if fill and stroke:
        return {"kind": "FillStroke", "fill": fill, "stroke": stroke}
    elif fill:
        return fill
    elif stroke:
        return {"kind": "Fill", "color": "transparent"}
    else:
        return {"kind": "Fill", "color": "black"}


def _processSolidStroke(symbol, options):
    color = _extractStrokeColor(symbol)
    opacity = _extractOpacity(symbol)
    width = _ptToPxProp(symbol, 'width', 1)
    return {"kind": "Stroke", "color": color, "opacity": opacity, "width": width}


def _processHatchFill(symbol, options):
    angle = symbol["angle"]
    angle = math.radians(angle) if angle else 0
    stroke = _processSolidStroke(symbol["stroke"], options)
    return {"kind": "Hatch", "angle": angle, "stroke": stroke}


def _processGradientFill(symbol, options):
    type = symbol.get("type", "Linear")
    if type == "Linear":
        rotation = symbol.get("angle", 0)
        rotation = math.radians(rotation)
        rotation = (rotation + math.pi / 2) % (2 * math.pi)
        stops = []
        for color in symbol["colorStops"]:
            offset = color["offset"]
            if offset < 0:
                offset = 0
            elif offset > 100:
                offset = 100
            stops.append((offset / 100, _parseColor(color["color"])))
        return {"kind": "LinearGradient", "stops": stops, "angle": rotation}
    else:
        _warnings.append("Unsupported gradient type: %s" % str(type))
        return {}


def _ptToPxProp(symbol, prop, defaultValue, integer=False):
    ptValue = symbol.get(prop, defaultValue)
    return pt_to_px(ptValue, integer)


def _extractFillColor(symbol):
    color = symbol.get("color")
    if color:
        return _parseColor(color)
    else:
        return "#000000"


def _extractStrokeColor(symbol):
    stroke = symbol.get("color", None)
    if stroke:
        return _parseColor(stroke)
    else:
        return "#000000"


def _parseColor(color):
    if isinstance(color, dict):
        red = color.get("r", 0)
        green = color.get("g", 0)
        blue = color.get("b", 0)
        alpha = color.get("a", 1)
        return f"rgba({red * 255}, {green * 255}, {blue * 255}, {alpha})"
    else:
        return color


def _extractOpacity(symbol):
    return symbol.get("transparency", 0) / 100


def _createUniqueValueFilter(fields, item):
    fieldValues = item.get("fieldValues")
    if fieldValues:
        expressions = []
        for field, value in fieldValues.items():
            if field in fields:
                expressions.append(["==", ["PropertyName", field], value])
            else:
                return None
        if len(expressions) > 1:
            return ["And"] + expressions
        else:
            return expressions[0]
    else:
        return None


def _getSymbolRotationFromVisualVariables(renderer, tolowercase=False):
    rotation = None
    if "visualVariables" in renderer:
        for visualVariable in renderer["visualVariables"]:
            if (
                visualVariable["type"] == "RotationExpression"
                and visualVariable["field"]
            ):
                rotation = processRotationExpression(visualVariable, tolowercase)
    return rotation


def _extractRotationAngle(rotationProps, rotationField):
    angle = rotationProps.get("angle", 0)
    angleField = rotationProps.get("field")
    if angleField and angleField == rotationField:
        angle = 0
    return angle


# def convert_styles(lyrx_content, output_path):
#     try:
#         geostyler, _, warnings = togeostyler.convert(lyrx_content)
#         if warnings:
#             print("Warnings occurred during conversion:", warnings)
#         if isinstance(geostyler, dict):  # Check if geostyler is a dictionary
#             with open(output_path, 'w') as f:
#                 f.write(json.dumps(geostyler))  # Convert dictionary to string before writing to file
#             return "Conversion completed successfully!"
#         else:
#             return "Invalid geostyler format. Expected dictionary."
#     except Exception as e:
#         return str(e)



# def process_styles(lyrx_content, output_path):
#     try:
#         geostyler, _, warnings = togeostyler.convert(lyrx_content)
#         if warnings:
#             print("Warnings occurred during conversion:", warnings)
#         with open(output_path, 'w') as f:
#             f.write(json.dumps(geostyler))  # Convert dictionary to string before writing to file
#         return "Conversion completed successfully!"
#     except Exception as e:
#         return str(e)


