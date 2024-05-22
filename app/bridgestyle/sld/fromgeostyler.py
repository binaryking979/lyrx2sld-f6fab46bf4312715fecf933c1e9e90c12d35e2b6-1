import os
import re
from xml.dom import minidom
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

from ..qgis.expressions import (
    OGC_PROPERTYNAME,
    OGC_IS_EQUAL_TO,
    OGC_IS_NULL,
    OGC_IS_LIKE
)
from .transformations import processTransformation
from ..version import __version__
from ..geostyler.custom_properties import WellKnownText

_warnings = []


def convert(geostyler, options=None):
    global _warnings
    _warnings = []
    attribs = {
        "version": "1.0.0",
        "xsi:schemaLocation": "http://www.opengis.net/sld StyledLayerDescriptor.xsd",
        "xmlns": "http://www.opengis.net/sld",
        "xmlns:ogc": "http://www.opengis.net/ogc",
        "xmlns:xlink": "http://www.w3.org/1999/xlink",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    root = Element("StyledLayerDescriptor", attrib=attribs)
    namedLayer = SubElement(root, "NamedLayer")
    layerName = SubElement(namedLayer, "Name")
    layerName.text = _replaceSpecialCharacters('_', geostyler.get("name", "default"))
    userStyle = SubElement(namedLayer, "UserStyle")
    userStyleTitle = SubElement(userStyle, "Title")
    userStyleTitle.text = geostyler.get("name")

    featureTypeStyle = SubElement(userStyle, "FeatureTypeStyle")
    if "transformation" in geostyler:
        featureTypeStyle.append(processTransformation(geostyler["transformation"]))
    for rule in geostyler.get("rules", []):
        featureTypeStyle.append(processRule(rule))
    if "blendMode" in geostyler:
        _addVendorOption(featureTypeStyle, "composite", geostyler["blendMode"])

    root.insert(0, ElementTree.Comment(f'Generated by bridge_style ({__version__})'))
    sldstring = ElementTree.tostring(root, encoding="utf-8", method="xml").decode()
    dom = minidom.parseString(sldstring)
    result = dom.toprettyxml(indent="  ", encoding="utf-8").decode(), _warnings
    return result


def processRule(rule):
    ruleElement = Element("Rule")
    ruleName = SubElement(ruleElement, "Name")
    ruleName.text = _replaceSpecialCharacters('_', rule.get("name", "default"))
    ruleTitle = SubElement(ruleElement, "Title")
    ruleTitle.text = rule.get("name", "")

    ruleFilter = rule.get("filter", None)
    if ruleFilter == "ELSE":
        filterElement = Element("ElseFilter")
        ruleElement.append(filterElement)
    else:
        filt = convertExpression(ruleFilter)
        if filt is not None:
            filterElement = Element("ogc:Filter")
            filterElement.append(filt)
            ruleElement.append(filterElement)
    if "scaleDenominator" in rule:
        scale = rule["scaleDenominator"]
        if "min" in scale:
            minScale = SubElement(ruleElement, "MinScaleDenominator")
            minScale.text = str(scale["min"])
        if "max" in scale:
            maxScale = SubElement(ruleElement, "MaxScaleDenominator")
            maxScale.text = str(scale["max"])
    symbolizers = _createSymbolizers(rule["symbolizers"])
    ruleElement.extend(symbolizers)

    return ruleElement


def _replaceSpecialCharacters(replacement, text=""):
    """
    Replace all characters that are not matching one of [a-zA-Z0-9_].
    """
    return re.sub('[^\w]', replacement, text)


def _createSymbolizers(symbolizers) -> list:
    sldSymbolizers = []
    for sl in symbolizers:
        symbolizer = _createSymbolizer(sl)
        if symbolizer is not None:
            if isinstance(symbolizer, list):
                sldSymbolizers.extend(symbolizer)
            else:
                sldSymbolizers.append(symbolizer)

    return sldSymbolizers


def _createSymbolizer(sl):
    symbol_type = sl["kind"]
    symbol_func = {
        "Icon": _iconSymbolizer,
        "Line": _lineSymbolizer,
        "Fill": _fillSymbolizer,
        "Mark": _markSymbolizer,
        "Text": _textSymbolizer,
        "Raster": _rasterSymbolizer,
    }.get(symbol_type, None)

    if not symbol_func:
        return None

    symbolizer = symbol_func(sl)
    if not isinstance(symbolizer, list):
        symbolizer = [symbolizer]
    for s in symbolizer:
        geom = _geometryFromSymbolizer(sl)
        if geom is not None:
            s.insert(0, geom)

    return symbolizer


def _symbolProperty(sl, name, default=None):
    if name in sl:
        return _processProperty(sl[name])
    else:
        return default


def _processProperty(value):
    v = convertExpression(value)
    if isinstance(v, Element) and v.tag == "ogc:Literal":
        v = v.text
    return v


def _addValueToElement(element, value):
    if value is not None:
        if isinstance(value, Element):
            element.append(value)
        else:
            element.text = str(value)


def _addCssParameter(parent, name, value):
    if value is not None:
        sub = SubElement(parent, "CssParameter", name=name)
        _addValueToElement(sub, value)
        return sub


def _addSubElement(parent, tag, value=None, attrib={}):
    strAttrib = {k: str(v) for k, v in attrib.items()}
    sub = SubElement(parent, tag, strAttrib)
    _addValueToElement(sub, value)
    return sub


def _addVendorOption(parent, name, value):
    if value is not None:
        sub = SubElement(parent, "VendorOption", name=name)
        _addValueToElement(sub, value)
        return sub


def _rasterSymbolizer(sl):
    opacity = sl["opacity"]
    root = Element("RasterSymbolizer")
    _addSubElement(root, "Opacity", opacity)

    channelSelectionElement = _addSubElement(root, "ChannelSelection")
    for chanName in ["grayChannel", "redChannel", "greenChannel", "blueChannel"]:
        if chanName in sl["channelSelection"]:
            sldChanName = chanName[0].upper() + chanName[1:]
            channel = _addSubElement(channelSelectionElement, sldChanName)
            _addSubElement(
                channel,
                "SourceChannelName",
                sl["channelSelection"][chanName]["sourceChannelName"],
            )

    if "colorMap" in sl:
        colMap = sl["colorMap"]
        colMapElement = _addSubElement(
            root, "ColorMap", None, {"type": sl["colorMap"]["type"]}
        )
        for entry in colMap["colorMapEntries"]:
            attribs = {
                "color": entry["color"],
                "quantity": entry["quantity"],
                "label": entry["label"],
                "opacity": entry["opacity"],
            }
            _addSubElement(colMapElement, "ColorMapEntry", None, attribs)

    return root


def _textSymbolizer(sl):
    color = _symbolProperty(sl, "color")
    fontFamily = _symbolProperty(sl, "font")
    label = _symbolProperty(sl, "label")
    size = _symbolProperty(sl, "size")

    root = Element("TextSymbolizer")
    _addSubElement(root, "Label", label)
    fontElem = _addSubElement(root, "Font")
    _addCssParameter(fontElem, "font-family", fontFamily)
    _addCssParameter(fontElem, "font-size", size)

    if "offset" in sl:
        placement = _addSubElement(root, "LabelPlacement")
        pointPlacement = _addSubElement(placement, "PointPlacement")
        if "anchor" in sl:
            anchor = sl["anchor"]
            # TODO: Use anchor
        # centers
        anchorLoc = _addSubElement(pointPlacement, "AnchorPoint")
        _addSubElement(anchorLoc, "AnchorPointX", _symbolProperty(sl, "anchorPointX",  0.5))
        _addSubElement(anchorLoc, "AnchorPointY", _symbolProperty(sl, "anchorPointY",  0.5))

        displacement = _addSubElement(pointPlacement, "Displacement")
        offset = sl["offset"]
        offsetx = _processProperty(offset[0])
        offsety = _processProperty(offset[1])
        _addSubElement(displacement, "DisplacementX", offsetx)
        _addSubElement(displacement, "DisplacementY", offsety)
        if "rotate" in sl:
            rotation = _symbolProperty(sl, "rotate")
            _addSubElement(pointPlacement, "Rotation", rotation)
    elif "perpendicularOffset" in sl and "background" not in sl:
        placement = _addSubElement(root, "LabelPlacement")
        linePlacement = _addSubElement(placement, "LinePlacement")
        offset = sl["perpendicularOffset"]
        dist = _processProperty(offset)
        _addSubElement(linePlacement, "PerpendicularOffset", dist)

    if "haloColor" in sl and "haloSize" in sl:
        haloElem = _addSubElement(root, "Halo")
        _addSubElement(haloElem, "Radius", sl["haloSize"])
        haloFillElem = _addSubElement(haloElem, "Fill")
        _addCssParameter(haloFillElem, "fill", sl["haloColor"])
        _addCssParameter(haloFillElem, "fill-opacity", sl["haloOpacity"])

    fillElem = _addSubElement(root, "Fill")
    _addCssParameter(fillElem, "fill", color)

    followLine = sl.get("followLine", False)
    if followLine:
        _addVendorOption(root, "followLine", True)
    elif "background" not in sl:
        _addVendorOption(root, "autoWrap", 50)
    group = "yes" if sl.get("group", True) else "no"
    _addVendorOption(root, "group", group)

    if "background" in sl:
        background = sl["background"]
        avg_size = max(background["sizeX"], background["sizeY"])
        shapeName = "rectangle"
        if background["shapeType"] == "circle" or background["shapeType"] == "elipse":
            shapeName = "circle"
        graphic = _addSubElement(root, "Graphic")
        mark = _addSubElement(graphic, "Mark")
        _addSubElement(graphic, "Opacity", background["opacity"])
        _addSubElement(mark, "WellKnownName", shapeName)
        fill = _addSubElement(mark, "Fill")
        stroke = _addSubElement(mark, "Stroke")
        _addCssParameter(stroke, "stroke", background["strokeColor"])
        _addCssParameter(fill, "fill", background["fillColor"])
        if background["sizeType"] == "buffer":
            _addVendorOption(root, "graphic-resize", "stretch")
            _addVendorOption(root, "graphic-margin", str(avg_size))
            _addVendorOption(root, "spaceAround", str(25))
        else:
            _addSubElement(graphic, "Size", str(avg_size))

        placement = _addSubElement(root, "LabelPlacement")
        pointPlacement = _addSubElement(placement, "PointPlacement")
        # centers
        achorLoc = _addSubElement(pointPlacement, "AnchorPoint")
        _addSubElement(achorLoc, "AnchorPointX", "0.5")
        _addSubElement(achorLoc, "AnchorPointY", "0.5")

    return root


def _lineSymbolizer(sl, graphicStrokeLayer=0):
    opacity = _symbolProperty(sl, "opacity")
    color = sl.get("color", None)
    graphicStroke = sl.get("graphicStroke", None)
    width = _symbolProperty(sl, "width")
    dasharray = _symbolProperty(sl, "dasharray")
    cap = _symbolProperty(sl, "cap")
    join = _symbolProperty(sl, "join")
    offset = _symbolProperty(sl, "perpendicularOffset")

    root = Element("LineSymbolizer")
    symbolizers = [root]
    stroke = _addSubElement(root, "Stroke")
    if graphicStroke is not None:
        graphicStrokeElement = _addSubElement(stroke, "GraphicStroke")
        graphic = _graphicFromSymbolizer(graphicStroke[graphicStrokeLayer])
        graphicStrokeElement.append(graphic[0])
        interval = sl.get("graphicStrokeInterval")
        dashOffset = sl.get("graphicStrokeOffset")
        size = graphicStroke[graphicStrokeLayer].get("size")
        try:
            fsize = float(size)
            finterval = float(interval)
            _addCssParameter(
                stroke, "stroke-dasharray", "%s %s" % (str(fsize), str(finterval))
            )
        except TypeError:
            pass
        _addCssParameter(stroke, "stroke-dashoffset", dashOffset)
        if graphicStrokeLayer == 0 and len(graphicStroke) > 1:
            for i in range(1, len(graphicStroke)):
                symbolizers.extend(_lineSymbolizer(sl, i))
    if color is not None:
        _addCssParameter(stroke, "stroke", color)
        _addCssParameter(stroke, "stroke-width", width)
        _addCssParameter(stroke, "stroke-opacity", opacity)
        _addCssParameter(stroke, "stroke-linejoin", join)
        _addCssParameter(stroke, "stroke-linecap", cap)
    if dasharray is not None:
        if cap != "butt":
            try:
                EXTRA_GAP = 2 * width
                tokens = [
                    int(v) + EXTRA_GAP if i % 2 else int(v)
                    for i, v in enumerate(dasharray.split(" "))
                ]
            except:  # in case width is not a number, but an expression
                GAP_FACTOR = 2
                tokens = [
                    int(v) * GAP_FACTOR if i % 2 else int(v)
                    for i, v in enumerate(dasharray.split(" "))
                ]
            dasharray = " ".join([str(v) for v in tokens])
        _addCssParameter(stroke, "stroke-dasharray", dasharray)
    if offset is not None:
        _addSubElement(root, "PerpendicularOffset", offset)
    return symbolizers


def _geometryFromSymbolizer(sl):
    geomExpr = convertExpression(sl.get("Geometry", None))
    if geomExpr is not None:
        geomElement = Element("Geometry")
        geomElement.append(geomExpr)
        return geomElement


def _iconSymbolizer(sl):
    path = sl["image"]
    if path.lower().endswith("svg"):
        return _svgMarkerSymbolizer(sl)
    else:
        return _rasterImageMarkerSymbolizer(sl)


def _svgMarkerSymbolizer(sl):
    root, graphic = _basePointSimbolizer(sl)
    svg = _svgGraphic(sl)
    graphic.insert(0, svg)
    return root


def _rasterImageMarkerSymbolizer(sl):
    root, graphic = _basePointSimbolizer(sl)
    img = _rasterImageGraphic(sl)
    graphic.insert(0, img)
    return root


def _markSymbolizer(sl):
    root, graphic = _basePointSimbolizer(sl)
    mark = _markGraphic(sl)
    graphic.insert(0, mark)
    return root


def _basePointSimbolizer(sl):
    size = _symbolProperty(sl, "size")
    rotation = _symbolProperty(sl, "rotate")
    opacity = _symbolProperty(sl, "opacity")
    offset = sl.get("offset", None)
    inclusion = sl.get("inclusion")

    root = Element("PointSymbolizer")
    graphic = _addSubElement(root, "Graphic")
    _addSubElement(graphic, "Opacity", opacity)
    _addSubElement(graphic, "Size", size)
    _addSubElement(graphic, "Rotation", rotation)
    if offset:
        displacement = _addSubElement(graphic, "Displacement")
        _addSubElement(displacement, "DisplacementX", offset[0])
        _addSubElement(displacement, "DisplacementY", offset[1])
    if inclusion:
        _addVendorOption(root, "inclusion", inclusion)

    return root, graphic


def _markGraphic(sl):
    color = _symbolProperty(sl, "color")
    strokeColor = _symbolProperty(sl, "strokeColor")
    fillOpacity = _symbolProperty(sl, "fillOpacity", 1.0)
    strokeOpacity = _symbolProperty(sl, "strokeOpacity", 1.0)
    strokeWidth = _symbolProperty(sl, "strokeWidth")
    outlineDasharray = _symbolProperty(sl, "outlineDasharray")
    shape = _symbolProperty(sl, "wellKnownName")
    mark = Element("Mark")
    _addSubElement(mark, "WellKnownName", shape)
    if fillOpacity:
        fill = SubElement(mark, "Fill")
        _addCssParameter(fill, "fill", color)
        _addCssParameter(fill, "fill-opacity", fillOpacity)
    stroke = _addSubElement(mark, "Stroke")
    if strokeOpacity:
        _addCssParameter(stroke, "stroke", strokeColor)
        _addCssParameter(stroke, "stroke-width", strokeWidth)
        _addCssParameter(stroke, "stroke-opacity", strokeOpacity)
        if outlineDasharray is not None:
            _addCssParameter(stroke, "stroke-dasharray", outlineDasharray)

    return mark


def _svgGraphic(sl):
    path = os.path.basename(sl["image"])
    color = _symbolProperty(sl, "color")
    outlineColor = _symbolProperty(sl, "strokeColor")
    outlineWidth = _symbolProperty(sl, "strokeWidth")
    mark = Element("Mark")
    _addSubElement(mark, "WellKnownName", "file://%s" % path)
    fill = _addSubElement(mark, "Fill")
    _addCssParameter(fill, "fill", color)
    stroke = _addSubElement(mark, "Stroke")
    _addCssParameter(stroke, "stroke", outlineColor)
    _addCssParameter(stroke, "stroke-width", outlineWidth)
    return mark


def _rasterImageGraphic(sl):
    path = os.path.basename(sl["image"])
    externalGraphic = Element("ExternalGraphic")
    attrib = {"xlink:type": "simple", "xlink:href": path}
    SubElement(externalGraphic, "OnlineResource", attrib=attrib)
    _addSubElement(
        externalGraphic, "Format", "image/%s" % os.path.splitext(path)[1][1:]
    )
    return externalGraphic


def _baseFillSymbolizer(sl):
    root = Element("PolygonSymbolizer")
    return root


def _graphicFromSymbolizer(sl):
    symbolizers = _createSymbolizer(sl)
    graphics = []
    for s in symbolizers:
        graphics.extend([graph for graph in s.iter("Graphic")])
    return graphics


def _fillSymbolizer(sl, graphicFillLayer=0):
    root = _baseFillSymbolizer(sl)
    symbolizers = [root]
    opacity = float(_symbolProperty(sl, "opacity", 1))
    color = sl.get("color", None)
    graphicFill = sl.get("graphicFill", None)
    offset = sl.get("offset", None)
    margin = sl.get("graphicFillMargin")

    if graphicFill is not None:
        if margin:
            _addVendorOption(root, "graphic-margin", " ".join([str(m) for m in margin]))
        elif _symbolProperty(sl, "graphicFillMarginY") and _symbolProperty(sl, "graphicFillMarginX"):
            margin = [_symbolProperty(sl, "graphicFillMarginY"), _symbolProperty(sl, "graphicFillMarginX")]
            _addVendorOption(root, "graphic-margin", " ".join(margin))
        else:
            margin = _symbolProperty(sl, "graphicFillMarginX")
            _addVendorOption(root, "graphic-margin", margin)
        fill = _addSubElement(root, "Fill")
        graphicFillElement = _addSubElement(fill, "GraphicFill")
        graphic = _graphicFromSymbolizer(graphicFill[graphicFillLayer])
        graphicFillElement.append(graphic[0])
        if graphicFillLayer == 0 and len(graphicFill) > 1:
            for i in range(1, len(graphicFill)):
                symbolizers.extend(_fillSymbolizer(sl, i))
    if color is not None:
        fillOpacity = float(_symbolProperty(sl, "fillOpacity", 1))
        fill = _addSubElement(root, "Fill")
        _addCssParameter(fill, "fill", color)
        _addCssParameter(fill, "fill-opacity", fillOpacity * opacity)

    outlineColor = _symbolProperty(sl, "outlineColor")
    if outlineColor is not None:
        outlineDasharray = _symbolProperty(sl, "outlineDasharray")
        outlineWidth = _symbolProperty(sl, "outlineWidth")
        outlineOpacity = float(_symbolProperty(sl, "outlineOpacity"))
        # borderWidthUnits = props["outline_width_unit"]
        stroke = _addSubElement(root, "Stroke")
        _addCssParameter(stroke, "stroke", outlineColor)
        _addCssParameter(stroke, "stroke-width", outlineWidth)
        _addCssParameter(stroke, "stroke-opacity", outlineOpacity * opacity)
        # _addCssParameter(stroke, "stroke-linejoin", join)
        # _addCssParameter(stroke, "stroke-linecap", cap)
        if outlineDasharray is not None:
            _addCssParameter(
                stroke, "stroke-dasharray", outlineDasharray
            )

    if offset:
        pass  # TODO: Not sure how to add this in SLD

    return symbolizers


#######################

expression_keys = {
    OGC_PROPERTYNAME,
    "Or",
    "And",
    OGC_IS_EQUAL_TO,
    "PropertyIsNotEqualTo",
    "PropertyIsLessThanOrEqualTo",
    "PropertyIsGreaterThanOrEqualTo",
    "PropertyIsLessThan",
    "PropertyIsGreaterThan",
    OGC_IS_LIKE,
    OGC_IS_NULL,
    "Add",
    "Sub",
    "Mul",
    "Div",
    "Not",
}

operatorToFunction = {
    OGC_IS_EQUAL_TO: "equalTo",
    "PropertyIsNotEqualTo": "notEqual",
    "PropertyIsLessThanOrEqualTo": "lessEqualThan",
    "PropertyIsGreaterThanOrEqualTo": "greaterEqualThan",
    "PropertyIsLessThan": "lessThan",
    "PropertyIsGreaterThan": "greaterThan",
}


def convertExpression(exp, inFunction=False):
    if exp is None:
        return None
    elif isinstance(exp, list):
        if exp[0] in expression_keys and not (inFunction and exp[0] in operatorToFunction):
            return handleOperator(exp)
        else:
            return handleFunction(exp)
    else:
        return handleLiteral(exp)


def handleOperator(exp):
    name = exp[0]
    elem = Element("ogc:" + name)
    if name == OGC_IS_LIKE:
        elem.attrib["wildCard"] = "%"
    if name == OGC_PROPERTYNAME:
        elem.text = exp[1]
    else:
        for operand in exp[1:]:
            if operand is None:
                continue
            elem.append(convertExpression(operand))
    return elem


def handleFunction(exp):
    name = operatorToFunction.get(exp[0], exp[0])
    if name == "to_string" and len(exp) == 2:
        # Special case: SLD/OGC does not know a "cast to string" function
        return handleLiteral(exp[1])
    elem = Element("ogc:Function", name=name)
    if len(exp) > 1:
        for arg in exp[1:]:
            if arg is None:
                continue
            elem.append(convertExpression(arg, True))
    return elem


def handleLiteral(v):
    specialLiteralElem = handleSpecialLiteral(v)
    if (specialLiteralElem is not None):
        return specialLiteralElem
    elem = Element("ogc:Literal")
    elem.text = str(v)
    return elem


def handleSpecialLiteral(v):
    if v == WellKnownText.NEW_LINE:
        elem = Element("ogc:Literal")
        elem.append(createCDATA("\n"))
        return elem
    return None


def createCDATA(text=None):
    element = Element("![CDATA[")
    element.text = text
    return element
