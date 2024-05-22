import os
import traceback

import json
from fastapi import FastAPI, status, Response
from fastapi.responses import JSONResponse
from bridgestyle.arcgis import togeostyler
# Initialize the FastAPI app
app = FastAPI()

# Define the route to convert lyrx to Geostyler format
@app.get("/v1/convert-styles/")
async def convert_styles():

    # Path to the folder containing the ArcGIS Pro lyrx documents
    # styles_folder = "styles"

    warnings = []

    try:        

        # Function to convert a single lyrx file to JSON
        def lyrx_to_json(lyrx_file_path):
            try:
                with open(lyrx_file_path, "r") as lyrx_file:
                    json_data = json.load(lyrx_file)
                return json_data
            except Exception as e:
                print(f"Error converting {lyrx_file_path} to JSON:", e)
                return None

        # Directory containing lyrx files
        lyrx_dir = "styles"

        # Output directory for JSON files
        output_dir = "json_files"

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Iterate over lyrx files in the directory
        for filename in os.listdir(lyrx_dir):
            if filename.endswith(".lyrx"):
                lyrx_path = os.path.join(lyrx_dir, filename)
                # Convert lyrx to JSON
                json_data = lyrx_to_json(lyrx_path)
                if json_data:
                    # Write JSON to file
                    json_filename = os.path.splitext(filename)[0] + ".json"
                    json_path = os.path.join(output_dir, json_filename)
                    with open(json_path, "w") as json_file:
                        json.dump(json_data, json_file, indent=2)
                    print(f"Converted {lyrx_path} to {json_path}")

        # Log any warnings
        for warning in warnings:
            print(warning)

        return {"message": "Conversion completed successfully."}

    except Exception as e:
        # Log any errors
        errors = traceback.format_exception(None, e, e.__traceback__)
        for error in errors:
            print(error)

        # Return errors and warnings as JSON response
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                'warnings': warnings,
                'errors': errors
            }
        )

# Define handler for the root URL "/"
@app.get("/")
async def root():
    return {"message": "Welcome to the lyrx2sld converter API!"}
