import json
from collections import defaultdict

# ------------------------------
# STEP 1 — Load flattened.json
# ------------------------------
with open("flattened_form_keys.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# ------------------------------
# STEP 2 — Classify fields
# ------------------------------
boolean_groups_to_ask = [
    "Form PF (Investor Type)",
    "Type of Subscriber",
    "Share Class Type"
]

text_fields = {}
grouped_booleans = defaultdict(dict)
other_booleans = {}

for key in data.keys():
    # Determine group type
    section = next((grp for grp in boolean_groups_to_ask if grp.lower() in key.lower()), None)

    if section:
        grouped_booleans[section][key] = False
    elif any(word in key.lower() for word in ["check", "type", "status", "eligibility", "class"]):
        other_booleans[key] = False
    else:
        text_fields[key] = ""


# ------------------------------
# STEP 3 — Fill text fields
# ------------------------------
print("\n📝 Please provide the following details:\n")
mailing_checked = False  # Flag to ask the question only once

for key in text_fields.keys():
    short_name = key.split(".")[-2] if "." in key else key
    value = ""

    if "Address (Mailing)" in key and not mailing_checked:
        same = input("📮 Is mailing address same as registered address? (y/n): ").strip().lower()
        mailing_checked = True  # Ask only once

        if same == "y":
            # Copy all mailing fields from registered fields
            for mail_key in [k for k in text_fields if "Address (Mailing)" in k]:
                reg_key = mail_key.replace("Address (Mailing)", "Address (Registered)")
                if reg_key in text_fields:
                    text_fields[mail_key] = text_fields[reg_key]
            continue  # Skip individual mailing fields

        # If 'n', fall through to ask each mailing field manually

    # Ask input for other fields (including mailing if 'n')
    if not ("Address (Mailing)" in key and same == "y"):
        value = input(f"→ {short_name.replace('_', ' ').title()}: ").strip()
        text_fields[key] = value



# ------------------------------
# STEP 4 — Ask grouped type fields
# ------------------------------
print("\n✅ Now select category-type options:\n")
final_booleans = {}

for group_name, fields in grouped_booleans.items():
    print(f"\n--- {group_name} ---")
    options = list(fields.keys())

    # Display options
    for i, key in enumerate(options, start=1):
        opt_name = key.split(".")[-2].replace("_", " ").title()
        print(f"{i}. {opt_name}")

    # Ask user for selection
    while True:
        choice = input(f"Select one or multiple (comma-separated, e.g. 1,3): ").strip()
        try:
            indices = [int(i) for i in choice.split(",") if i.strip()]
            if all(1 <= idx <= len(options) for idx in indices):
                break
            else:
                print("❌ Invalid input, try again.")
        except ValueError:
            print("❌ Please enter numbers separated by commas.")

    # Mark selected options True
    for i, key in enumerate(options, start=1):
        final_booleans[key] = i in indices

# ------------------------------
# STEP 5 — Combine all fields
# ------------------------------
final_data = {**text_fields, **final_booleans, **other_booleans}

# ------------------------------
# STEP 6 — Save output
# ------------------------------
output_file = "final_output2.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(final_data, f, indent=4, ensure_ascii=False)

print(f"\n✅ Final JSON successfully saved to '{output_file}'")
print("\n🎯 Final Filled JSON Preview:\n")
print(json.dumps(final_data, indent=4, ensure_ascii=False))