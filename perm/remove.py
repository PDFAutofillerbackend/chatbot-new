import json

def flatten_json(data, parent_key='', sep='.'):
    """Recursively flattens a nested JSON/dict."""
    items = []
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.extend(flatten_json(value, new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)


# ---- FILE HANDLING ----
input_file = "form_keys.json"       # cleaned JSON (without descriptions)
output_file = "flattened_form_keys.json"   # flattened JSON result

with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

flattened_data = flatten_json(data)

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(flattened_data, f, indent=4)

print(f"✅ JSON flattened successfully! Saved to '{output_file}'")
