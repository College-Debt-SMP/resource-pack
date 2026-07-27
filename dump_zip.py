import zipfile
import json
import traceback

with open("zip_log.txt", "w") as out:
    try:
        zip_path = "Lightfall by MCTools.zip"
        with zipfile.ZipFile(zip_path, "r") as z:
            out.write("Files in zip:\n")
            for f in z.namelist():
                out.write(f + "\n")
            
            mctools_path = next((f for f in z.namelist() if f.lower().endswith("mctools.json")), None)
            if mctools_path:
                out.write(f"\nFound mctools at {mctools_path}\n")
                with z.open(mctools_path) as json_file:
                    data = json.load(json_file)
                    out.write(json.dumps(data, indent=2))
            else:
                out.write("\nNO MCTOOLS.JSON FOUND!\n")
    except Exception as e:
        out.write(f"Error: {e}\n")
        out.write(traceback.format_exc())
