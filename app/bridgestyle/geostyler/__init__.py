import json

def toGeostyler(style, options=None):
    return json.loads(style), [], []


def fromGeostyler(style, options=None):
    return json.dumps(style), [], []

# def convert_styles(arcgis_content, options=None):
#     geostyler, _, warnings = convert(arcgis_content, options)
#     # Check if geostyler is a dictionary
#     if isinstance(geostyler, dict):
#         with open('output.json', 'w') as f:
#             # Convert the geostyler dictionary to a JSON string
#             geostyler_json = json.dumps(geostyler)
#             f.write(geostyler_json)
#     else:
#         warnings.append("Invalid geostyler format. Expected dictionary, got %s" % type(geostyler))
#     return warnings

