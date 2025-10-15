# # smart_live_fill_final.py
# import os
# import json
# import uuid
# import datetime
# from dotenv import load_dotenv
# from collections import defaultdict

# # LangChain & OpenAI
# from langchain_openai import ChatOpenAI
# from langchain.chains import LLMChain
# from langchain_core.prompts import PromptTemplate
# from langchain.memory import ConversationBufferWindowMemory

# # NLP fallback
# import re
# import spacy
# from fuzzywuzzy import process

# # ------------------- Config -------------------
# load_dotenv()
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# if not OPENAI_API_KEY:
#     raise EnvironmentError("Set OPENAI_API_KEY in .env")

# # Single model for everything: gpt-4o-mini (best price/performance)
# llm_extraction = ChatOpenAI(
#     model="gpt-4o-mini",
#     temperature=0.0,  # Deterministic for extraction
#     openai_api_key=OPENAI_API_KEY
# )

# llm_conversation = ChatOpenAI(
#     model="gpt-4o-mini",
#     temperature=0.7,  # Natural conversation
#     openai_api_key=OPENAI_API_KEY
# )

# FORM_KEYS_FILE = "form_keys.json"
# MANDATORY_FILE = "mandatory.json"
# MEMORY_BUFFER_SIZE = 8

# # Load spaCy
# try:
#     nlp = spacy.load("en_core_web_sm")
# except:
#     nlp = None
#     print("⚠️ spaCy not loaded. Install with: python -m spacy download en_core_web_sm")

# # ------------------- Utilities -------------------
# def load_json(path):
#     with open(path, "r", encoding="utf-8") as f:
#         return json.load(f)

# def save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)

# def create_session_folder(root="chatbot_sessions"):
#     session_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
#     session_folder = os.path.join(root, session_name)
#     os.makedirs(session_folder, exist_ok=True)
#     return session_folder

# def flatten_dict(d, parent_key="", sep="."):
#     items = {}
#     for k, v in d.items():
#         new_key = f"{parent_key}{sep}{k}" if parent_key else k
#         if isinstance(v, dict):
#             items.update(flatten_dict(v, new_key, sep=sep))
#         else:
#             items[new_key] = v
#     return items

# def unflatten_dict(d, sep="."):
#     result = {}
#     for k, v in d.items():
#         keys = k.split(sep)
#         ref = result
#         for sub in keys[:-1]:
#             if sub not in ref:
#                 ref[sub] = {}
#             ref = ref[sub]
#         ref[keys[-1]] = v
#     return result

# def deep_update(d, updates):
#     for k, v in updates.items():
#         if isinstance(v, dict) and isinstance(d.get(k, None), dict):
#             deep_update(d[k], v)
#         else:
#             d[k] = v

# # ------------------- Fallback extractor -------------------
# COMMON_PATTERNS = {
#     "email": r"[\w\.-]+@[\w\.-]+\.\w+",
#     "phone": r"\+?\d[\d\s\-]{7,}\d",
#     "pan": r"[A-Z]{5}\d{4}[A-Z]",
# }

# def fallback_extract(user_input: str, form_keys_flat: dict):
#     extracted = {}
#     # Regex extraction
#     for name, pat in COMMON_PATTERNS.items():
#         m = re.search(pat, user_input)
#         if m:
#             extracted[name] = m.group().strip()
    
#     # NLP extraction
#     if nlp:
#         doc = nlp(user_input)
#         for ent in doc.ents:
#             label = ent.label_.lower()
#             if label in ["person", "org", "gpe", "loc", "date"]:
#                 extracted[label] = ent.text
    
#     # Fuzzy matching to form keys
#     mapped = {}
#     for short_label, value in extracted.items():
#         result = process.extractOne(short_label, list(form_keys_flat.keys()))
#         if result:
#             candidate_key, score = result
#             if score >= 65:
#                 mapped[candidate_key] = value
    
#     return mapped

# # ------------------- LLM extraction -------------------
# EXTRACT_PROMPT = PromptTemplate(
#     input_variables=["schema_json", "user_input", "chat_history"],
#     template="""You are an assistant that extracts structured form data from user input.

# Conversation history:
# {chat_history}

# Available form fields (use exact keys):
# {schema_json}

# User message: "{user_input}"

# Return ONLY a valid JSON object with extracted fields. Keys MUST match the form fields exactly.
# If nothing can be extracted, return {{}}.

# Example output: {{"Name": "John Doe", "Email ID": "john@example.com"}}

# JSON:"""
# )

# extract_chain = LLMChain(llm=llm_extraction, prompt=EXTRACT_PROMPT)

# def llm_extract(user_input: str, chat_history: str, live_fill_flat: dict):
#     # Send subset of keys to save tokens (most relevant ones)
#     schema_keys = list(live_fill_flat.keys())[:100]
#     schema_json = json.dumps(schema_keys, ensure_ascii=False)
    
#     try:
#         result = extract_chain.invoke({
#             "schema_json": schema_json,
#             "user_input": user_input,
#             "chat_history": chat_history
#         })
#         raw = result.get('text', '{}')
#         parsed = json.loads(raw)
#         # Filter to only valid keys
#         filtered = {k: v for k, v in parsed.items() if k in live_fill_flat}
#         return filtered
#     except Exception as e:
#         print(f"⚠️ LLM extraction failed: {e}")
#         return None

# # ------------------- Natural conversation -------------------
# CONVERSATION_PROMPT = PromptTemplate(
#     input_variables=["extracted_fields", "missing_count", "chat_history"],
#     template="""You are a friendly onboarding assistant helping someone fill out a form.

# Conversation so far:
# {chat_history}

# Just captured: {extracted_fields}
# Still need: {missing_count} mandatory fields

# Generate ONE natural, friendly question (1 sentence max) asking if the user has more information to share.
# - Sound conversational and warm, not robotic
# - Don't mention "fields" or "data" or "mandatory"
# - Keep it casual and human

# Question:"""
# )

# conversation_chain = LLMChain(llm=llm_conversation, prompt=CONVERSATION_PROMPT)

# def generate_natural_followup(extracted: dict, missing_count: int, chat_history: str):
#     try:
#         result = conversation_chain.invoke({
#             "extracted_fields": list(extracted.keys()) if extracted else "nothing new",
#             "missing_count": missing_count,
#             "chat_history": chat_history
#         })
#         return result.get('text', '').strip()
#     except:
#         # Fallback questions
#         if missing_count > 15:
#             return "Got it! Anything else you'd like to share before I ask specific questions?"
#         elif missing_count > 5:
#             return "Thanks! Want to add anything else?"
#         else:
#             return "Perfect! Anything more you'd like to mention?"

# # ------------------- Field Mapping Helper -------------------
# def resolve_field_mapping(mandatory_data: dict, form_keys_flat: dict):
#     """
#     Resolve mandatory field mappings to actual form_keys paths.
#     mandatory.json structure: "Human Name": "field_id" or nested
#     form_keys.json structure: "Section.field_id.value": ""
    
#     This function finds the actual paths in form_keys for each mandatory field.
#     """
#     resolved = {}
    
#     def find_field_path(field_id: str):
#         """Find the path in form_keys that contains this field ID"""
#         if not field_id:
#             return None
#         for path in form_keys_flat.keys():
#             # Check if field_id is in the path
#             if field_id in path and path.endswith('.value'):
#                 return path
#         return None
    
#     def process_dict(d, parent_key=""):
#         """Recursively process mandatory structure"""
#         for key, value in d.items():
#             if isinstance(value, dict):
#                 # Nested structure, go deeper
#                 process_dict(value, key)
#             elif isinstance(value, str) and value:
#                 # String value = field ID mapping
#                 actual_path = find_field_path(value)
#                 if actual_path:
#                     resolved[actual_path] = ""
#             elif value == "":
#                 # Empty string, check if it's a section header
#                 # Look for fields under this section
#                 if parent_key:
#                     section_prefix = f"{parent_key}.{key}"
#                 else:
#                     section_prefix = key
                
#                 # Find any field that starts with this section
#                 for path in form_keys_flat.keys():
#                     if section_prefix in path or key.replace(" ", "").lower() in path.lower():
#                         resolved[path] = ""
    
#     process_dict(mandatory_data)
#     return resolved

# # ------------------- Helper functions -------------------
# def get_missing_mandatory_keys(live_fill_flat: dict, mandatory_flat: dict):
#     missing = []
#     for k in mandatory_flat:
#         val = live_fill_flat.get(k, "")
#         if not str(val).strip() or val == "" or val is None:
#             missing.append(k)
#     return missing

# def get_remaining_optional_keys(live_fill_flat: dict, mandatory_flat: dict):
#     optional = []
#     for k in live_fill_flat:
#         if k not in mandatory_flat:
#             val = live_fill_flat.get(k, "")
#             if not str(val).strip() or val == "" or val is None:
#                 optional.append(k)
#     return optional

# def classify_mandatory_fields(mandatory_keys):
#     """Separate text fields from boolean groups"""
#     boolean_groups = ["Form PF (Investor Type)", "Type of Subscriber", "Share Class"]
    
#     text_fields = []
#     grouped_booleans = defaultdict(list)
    
#     for key in mandatory_keys:
#         # Check if it's a boolean group field
#         section = next((grp for grp in boolean_groups if grp.lower() in key.lower()), None)
#         if section:
#             grouped_booleans[section].append(key)
#         else:
#             text_fields.append(key)
    
#     return text_fields, grouped_booleans

# def ask_text_fields_sequential(fields: list, live_fill_flat: dict, logs: list, form_keys_flat: dict):
#     """Ask text fields one by one (isolated code style)"""
#     filled = {}
#     mailing_checked = False
#     same = "n"
    
#     print("\n📝 Let me ask you a few specific questions:\n")
    
#     # Only ask for fields that exist and aren't already filled
#     fields_to_ask = []
#     for key in fields:
#         if key not in form_keys_flat:
#             logs.append({"warning": "field_not_in_form_keys", "field": key})
#             continue
        
#         # Check if already filled
#         current_value = live_fill_flat.get(key, "")
#         if current_value and str(current_value).strip():
#             print(f"✓ Already have: {key.split('.')[-2]} = {current_value}")
#             continue
        
#         fields_to_ask.append(key)
    
#     if not fields_to_ask:
#         print("✅ All mandatory fields already filled!")
#         return filled
    
#     for key in fields_to_ask:
#         # Get readable name from path
#         path_parts = key.split('.')
#         if len(path_parts) >= 2:
#             short_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
#         else:
#             short_name = key.replace("_", " ").title()
        
#         # Special handling for mailing address
#         if "mailing" in key.lower() and not mailing_checked:
#             same = input("\n📮 Is mailing address same as registered address? (y/n): ").strip().lower()
#             mailing_checked = True
            
#             if same == "y":
#                 # Find corresponding registered field
#                 for mail_key in [k for k in fields_to_ask if "mailing" in k.lower()]:
#                     reg_key = mail_key.replace("mailing", "registered")
#                     if reg_key in live_fill_flat and live_fill_flat[reg_key]:
#                         filled[mail_key] = live_fill_flat[reg_key]
#                         print(f"✓ Copied: {mail_key.split('.')[-2]}")
#                 continue
        
#         if "mailing" in key.lower() and same == "y":
#             continue
        
#         value = input(f"→ {short_name}: ").strip()
#         if value:
#             filled[key] = value
#             logs.append({"sequential_fill": {key: value}})
    
#     return filled

# def ask_grouped_boolean_fields(grouped_booleans: dict, logs: list):
#     """Ask boolean groups with multi-select, store as true/false"""
#     filled = {}
    
#     print("\n✅ Now let's select some categories:\n")
    
#     for group_name, fields in grouped_booleans.items():
#         print(f"\n--- {group_name} ---")
#         options = list(fields)
        
#         # Display options with improved name extraction
#         for i, key in enumerate(options, start=1):
#             path_parts = key.split(".")
            
#             # Try to find the meaningful part (not "value", not group name)
#             opt_name = None
#             for part in reversed(path_parts):
#                 clean_part = part.replace("_", " ").replace("ID", "").strip()
                
#                 # Skip generic terms
#                 if clean_part.lower() in ["value", "selected", "checkbox", "option"]:
#                     continue
                
#                 # Skip if it matches the group name
#                 if group_name and clean_part.lower() == group_name.lower():
#                     continue
                
#                 # Found a meaningful name
#                 opt_name = clean_part.title()
#                 break
            
#             # Fallback if nothing found
#             if not opt_name:
#                 opt_name = key.split(".")[-1].replace("_", " ").title()
            
#             print(f"{i}. {opt_name}")
        
#         # Get user selection
#         while True:
#             choice = input("Select one or multiple (comma-separated, e.g., 1,3): ").strip()
#             try:
#                 if not choice:  # Allow empty selection
#                     indices = []
#                     break
#                 indices = [int(i) for i in choice.split(",") if i.strip()]
#                 if all(1 <= idx <= len(options) for idx in indices):
#                     break
#                 else:
#                     print("❌ Invalid input. Try again.")
#             except ValueError:
#                 print("❌ Please enter numbers separated by commas.")
        
#         # Store as true/false (ONLY for selected options, rest stay as is)
#         for i, key in enumerate(options, start=1):
#             filled[key] = (i in indices)
#             logs.append({"boolean_selection": {key: filled[key]}})
    
#     return filled

# # ------------------- Main flow -------------------
# def main():
#     print("🌟 Welcome to Smart Form Assistant\n")
    
#     # Setup
#     session_folder = create_session_folder()
#     live_fill_file = os.path.join(session_folder, "live_fill.json")
#     log_file = os.path.join(session_folder, "log.json")
    
#     form_keys = load_json(FORM_KEYS_FILE)
#     mandatory_master = load_json(MANDATORY_FILE)
    
#     live_fill = form_keys.copy()
#     save_json(live_fill_file, live_fill)
    
#     logs = []
#     memory = ConversationBufferWindowMemory(k=MEMORY_BUFFER_SIZE, return_messages=False)
    
#     # ============ PHASE 1: Select Investor Type ============
#     mandatory_data = mandatory_master.get("Type of Investors", {})
#     investor_list = list(mandatory_data.keys())
    
#     if not investor_list:
#         print("❌ No investor types found. Exiting.")
#         return
    
#     print("Available Investor Types:")
#     for idx, t in enumerate(investor_list, start=1):
#         print(f"{idx}. {t}")
    
#     choice = input("\nEnter Investor Type (number or name): ").strip()
#     if choice.isdigit() and 1 <= int(choice) <= len(investor_list):
#         investor_type = investor_list[int(choice) - 1]
#     else:
#         investor_type = choice
    
#     if investor_type not in mandatory_data:
#         print("❌ Invalid type. Exiting.")
#         return
    
#     print(f"\n✅ Investor type selected: {investor_type}\n")
#     logs.append({"investor_type": investor_type})
    
#     # Flatten form_keys only
#     live_fill_flat = flatten_dict(live_fill)
    
#     # CRITICAL: Resolve mandatory field mappings (don't flatten mandatory first!)
#     print("🔄 Resolving field mappings...")
#     mandatory_flat = resolve_field_mapping(mandatory_data[investor_type], live_fill_flat)
#     print(f"✅ Mapped {len(mandatory_flat)} mandatory fields\n")
    
#     if not mandatory_flat:
#         print("⚠️ Warning: No valid mandatory fields found after mapping!")
#         print("Check that field IDs in mandatory.json match those in form_keys.json")
#         # Show example of expected vs actual
#         print("\nExample mandatory.json entry:")
#         print('  "Name": "investorFullLegalName_ID"')
#         print("\nExpected form_keys.json entry:")
#         print('  "Details in Subscription Booklet.investorFullLegalName_ID.value": ""')
#         return
    
#     # ============ PHASE 2: Conversational Information Gathering ============
#     print("💬 Tell me about yourself! Share any information in your own words.\n")
    
#     conversation_active = True
    
#     while conversation_active:
#         user_input = input("You: ").strip()
        
#         if not user_input:
#             continue
        
#         # Save to memory
#         memory.save_context({"input": user_input}, {"output": ""})
        
#         # Extract using LLM + fallback
#         chat_history = memory.load_memory_variables({}).get('history', '')
        
#         extracted = llm_extract(user_input, chat_history, live_fill_flat)
#         if not extracted:
#             extracted = fallback_extract(user_input, live_fill_flat)
#             logs.append({"extraction_method": "fallback", "result": extracted})
#         else:
#             logs.append({"extraction_method": "llm", "result": extracted})
        
#         # Update live_fill
#         if extracted:
#             deep_update(live_fill_flat, extracted)
#             save_json(live_fill_file, unflatten_dict(live_fill_flat))
#             save_json(log_file, logs)
        
#         # Generate natural follow-up
#         missing = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
#         followup = generate_natural_followup(extracted or {}, len(missing), chat_history)
        
#         print(f"\n💬 {followup}")
#         memory.save_context({"input": ""}, {"output": followup})
        
#         continue_input = input("→ ").strip().lower()
        
#         # Check if user wants to continue
#         if continue_input in ["no", "n", "nope", "done", "that's all", "nothing", "nah", "finish"]:
#             conversation_active = False
#             print("\n✅ Great! Let me gather a few more details.\n")
#         elif continue_input in ["yes", "y", "yeah", "sure", "yep", "ok", "okay", "more"]:
#             print("\n💬 Go ahead:\n")
#         else:
#             # Treat as more information and loop again
#             print()
    
#     # ============ PHASE 3: Ask Mandatory Fields One-by-One ============
#     missing_mandatory = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
    
#     if missing_mandatory:
#         # Separate text fields and boolean groups
#         text_fields, grouped_booleans = classify_mandatory_fields(missing_mandatory)
        
#         # Ask text fields sequentially
#         if text_fields:
#             filled_text = ask_text_fields_sequential(text_fields, live_fill_flat, logs, live_fill_flat)
#             deep_update(live_fill_flat, filled_text)
#             save_json(live_fill_file, unflatten_dict(live_fill_flat))
#             save_json(log_file, logs)
        
#         # Ask boolean grouped fields
#         if grouped_booleans:
#             filled_booleans = ask_grouped_boolean_fields(grouped_booleans, logs)
#             deep_update(live_fill_flat, filled_booleans)
#             save_json(live_fill_file, unflatten_dict(live_fill_flat))
#             save_json(log_file, logs)
    
#     print("\n✅ All mandatory fields filled!")
    
#     # ============ PHASE 4: Optional Fields ============
#     remaining_optional = get_remaining_optional_keys(live_fill_flat, mandatory_flat)
    
#     if remaining_optional:
#         opt_choice = input(f"\n🤔 There are {len(remaining_optional)} optional fields. Fill them? (yes/no): ").strip().lower()
        
#         if opt_choice in ["yes", "y"]:
#             filled_opt = ask_text_fields_sequential(remaining_optional, live_fill_flat, logs, live_fill_flat)
#             deep_update(live_fill_flat, filled_opt)
#             save_json(live_fill_file, unflatten_dict(live_fill_flat))
#             save_json(log_file, logs)
    
#     # ============ PHASE 5: Summary ============
#     print("\n🎉 Form completed successfully!\n")
#     print(f"📁 Session folder: {session_folder}")
#     print(f"📄 Live JSON: {live_fill_file}")
#     print(f"📝 Log file: {log_file}")
#     print("\n✅ All data saved. Thank you!")

# if __name__ == "__main__":
#     main()






# smart_live_fill_final.py
import os
import json
import uuid
import datetime
from dotenv import load_dotenv
from collections import defaultdict

# LangChain & OpenAI
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain_core.prompts import PromptTemplate
from langchain.memory import ConversationBufferWindowMemory

# NLP fallback
import re
import spacy
from fuzzywuzzy import process

# ------------------- Config -------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise EnvironmentError("Set OPENAI_API_KEY in .env")

# Single model for everything: gpt-4o-mini (best price/performance)
llm_extraction = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.0,  # Deterministic for extraction
    openai_api_key=OPENAI_API_KEY
)

llm_conversation = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,  # Natural conversation
    openai_api_key=OPENAI_API_KEY
)

FORM_KEYS_FILE = "form_keys.json"
MANDATORY_FILE = "mandatory.json"
MEMORY_BUFFER_SIZE = 8

# Load spaCy
try:
    nlp = spacy.load("en_core_web_sm")
except:
    nlp = None
    print("⚠️ spaCy not loaded. Install with: python -m spacy download en_core_web_sm")

# ------------------- Utilities -------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def create_session_folder(root="chatbot_sessions"):
    session_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    session_folder = os.path.join(root, session_name)
    os.makedirs(session_folder, exist_ok=True)
    return session_folder

def flatten_dict(d, parent_key="", sep="."):
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items

def unflatten_dict(d, sep="."):
    result = {}
    for k, v in d.items():
        keys = k.split(sep)
        ref = result
        for sub in keys[:-1]:
            if sub not in ref:
                ref[sub] = {}
            ref = ref[sub]
        ref[keys[-1]] = v
    return result

def deep_update(d, updates):
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(d.get(k, None), dict):
            deep_update(d[k], v)
        else:
            d[k] = v

# ------------------- Fallback extractor -------------------
COMMON_PATTERNS = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone": r"\+?\d[\d\s\-]{7,}\d",
    "pan": r"[A-Z]{5}\d{4}[A-Z]",
}

def fallback_extract(user_input: str, form_keys_flat: dict):
    extracted = {}
    # Regex extraction
    for name, pat in COMMON_PATTERNS.items():
        m = re.search(pat, user_input)
        if m:
            extracted[name] = m.group().strip()
    
    # NLP extraction
    if nlp:
        doc = nlp(user_input)
        for ent in doc.ents:
            label = ent.label_.lower()
            if label in ["person", "org", "gpe", "loc", "date"]:
                extracted[label] = ent.text
    
    # Fuzzy matching to form keys
    mapped = {}
    for short_label, value in extracted.items():
        result = process.extractOne(short_label, list(form_keys_flat.keys()))
        if result:
            candidate_key, score = result
            if score >= 65:
                mapped[candidate_key] = value
    
    return mapped

# ------------------- LLM extraction -------------------
EXTRACT_PROMPT = PromptTemplate(
    input_variables=["schema_json", "user_input", "chat_history"],
    template="""You are an assistant that extracts structured form data from user input.

Conversation history:
{chat_history}

Available form fields (use exact keys):
{schema_json}

User message: "{user_input}"

Return ONLY a valid JSON object with extracted fields. Keys MUST match the form fields exactly.
If nothing can be extracted, return {{}}.

Example output: {{"Name": "John Doe", "Email ID": "john@example.com"}}

JSON:"""
)

extract_chain = LLMChain(llm=llm_extraction, prompt=EXTRACT_PROMPT)

def llm_extract(user_input: str, chat_history: str, live_fill_flat: dict):
    # Send subset of keys to save tokens (most relevant ones)
    schema_keys = list(live_fill_flat.keys())[:100]
    schema_json = json.dumps(schema_keys, ensure_ascii=False)
    
    try:
        result = extract_chain.invoke({
            "schema_json": schema_json,
            "user_input": user_input,
            "chat_history": chat_history
        })
        raw = result.get('text', '{}')
        parsed = json.loads(raw)
        # Filter to only valid keys
        filtered = {k: v for k, v in parsed.items() if k in live_fill_flat}
        return filtered
    except Exception as e:
        print(f"⚠️ LLM extraction failed: {e}")
        return None

# ------------------- Natural conversation -------------------
CONVERSATION_PROMPT = PromptTemplate(
    input_variables=["extracted_fields", "missing_count", "chat_history"],
    template="""You are a friendly onboarding assistant helping someone fill out a form.

Conversation so far:
{chat_history}

Just captured: {extracted_fields}
Still need: {missing_count} mandatory fields

Generate ONE natural, friendly question (1 sentence max) asking if the user has more information to share.
- Sound conversational and warm, not robotic
- Don't mention "fields" or "data" or "mandatory"
- Keep it casual and human

Question:"""
)

conversation_chain = LLMChain(llm=llm_conversation, prompt=CONVERSATION_PROMPT)

def generate_natural_followup(extracted: dict, missing_count: int, chat_history: str):
    try:
        result = conversation_chain.invoke({
            "extracted_fields": list(extracted.keys()) if extracted else "nothing new",
            "missing_count": missing_count,
            "chat_history": chat_history
        })
        return result.get('text', '').strip()
    except:
        # Fallback questions
        if missing_count > 15:
            return "Got it! Anything else you'd like to share before I ask specific questions?"
        elif missing_count > 5:
            return "Thanks! Want to add anything else?"
        else:
            return "Perfect! Anything more you'd like to mention?"

# ------------------- Field Mapping Helper -------------------
def resolve_field_mapping(mandatory_data: dict, form_keys_flat: dict):
    """
    Resolve mandatory field mappings to actual form_keys paths.
    mandatory.json structure: "Human Name": "field_id" or nested
    form_keys.json structure: "Section.field_id.value": ""
    
    This function finds the actual paths in form_keys for each mandatory field.
    """
    resolved = {}
    
    def find_field_path(field_id: str):
        """Find the path in form_keys that contains this field ID"""
        if not field_id:
            return None
        for path in form_keys_flat.keys():
            # Check if field_id is in the path
            if field_id in path and path.endswith('.value'):
                return path
        return None
    
    def process_dict(d, parent_key=""):
        """Recursively process mandatory structure"""
        for key, value in d.items():
            if isinstance(value, dict):
                # Nested structure, go deeper
                process_dict(value, key)
            elif isinstance(value, str) and value:
                # String value = field ID mapping
                actual_path = find_field_path(value)
                if actual_path:
                    resolved[actual_path] = ""
            elif value == "":
                # Empty string, check if it's a section header
                # Look for fields under this section
                if parent_key:
                    section_prefix = f"{parent_key}.{key}"
                else:
                    section_prefix = key
                
                # Find any field that starts with this section
                for path in form_keys_flat.keys():
                    if section_prefix in path or key.replace(" ", "").lower() in path.lower():
                        resolved[path] = ""
    
    process_dict(mandatory_data)
    return resolved

# ------------------- Helper functions -------------------
def get_missing_mandatory_keys(live_fill_flat: dict, mandatory_flat: dict):
    missing = []
    for k in mandatory_flat:
        val = live_fill_flat.get(k, "")
        # Only empty strings and None are missing (not true/false booleans)
        if val == "" or val is None:
            missing.append(k)
    return missing

def get_remaining_optional_keys(live_fill_flat: dict, mandatory_flat: dict):
    optional = []
    for k in live_fill_flat:
        if k not in mandatory_flat:
            val = live_fill_flat.get(k, "")
            if not str(val).strip() or val == "" or val is None:
                optional.append(k)
    return optional

def classify_mandatory_fields(mandatory_keys):
    """Separate text fields from boolean groups"""
    boolean_groups = ["Form PF (Investor Type)", "Type of Subscriber", "Share Class"]
    
    text_fields = []
    grouped_booleans = defaultdict(list)
    
    for key in mandatory_keys:
        # Check if it's a boolean group field
        section = next((grp for grp in boolean_groups if grp.lower() in key.lower()), None)
        if section:
            grouped_booleans[section].append(key)
        else:
            text_fields.append(key)
    
    return text_fields, grouped_booleans

def get_all_boolean_fields_in_group(group_name, mandatory_flat, live_fill_flat):
    """Get ALL fields in a boolean group, regardless of current value"""
    all_fields = []
    for key in live_fill_flat.keys():
        if group_name.lower() in key.lower():
            all_fields.append(key)
    return all_fields

def ask_text_fields_sequential(fields: list, live_fill_flat: dict, logs: list, form_keys_flat: dict):
    """Ask text fields one by one (isolated code style)"""
    filled = {}
    mailing_checked = False
    same = "n"
    
    print("\n📝 Let me ask you a few specific questions:\n")
    
    # Only ask for fields that exist and aren't already filled
    fields_to_ask = []
    for key in fields:
        if key not in form_keys_flat:
            logs.append({"warning": "field_not_in_form_keys", "field": key})
            continue
        
        # Check if already filled
        current_value = live_fill_flat.get(key, "")
        if current_value and str(current_value).strip():
            print(f"✓ Already have: {key.split('.')[-2]} = {current_value}")
            continue
        
        fields_to_ask.append(key)
    
    if not fields_to_ask:
        print("✅ All mandatory fields already filled!")
        return filled
    
    for key in fields_to_ask:
        # Get readable name from path
        path_parts = key.split('.')
        if len(path_parts) >= 2:
            short_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
        else:
            short_name = key.replace("_", " ").title()
        
        # Special handling for mailing address
        if "mailing" in key.lower() and not mailing_checked:
            same = input("\n📮 Is mailing address same as registered address? (y/n): ").strip().lower()
            mailing_checked = True
            
            if same == "y":
                # Find corresponding registered field
                for mail_key in [k for k in fields_to_ask if "mailing" in k.lower()]:
                    reg_key = mail_key.replace("mailing", "registered")
                    if reg_key in live_fill_flat and live_fill_flat[reg_key]:
                        filled[mail_key] = live_fill_flat[reg_key]
                        print(f"✓ Copied: {mail_key.split('.')[-2]}")
                continue
        
        if "mailing" in key.lower() and same == "y":
            continue
        
        value = input(f"→ {short_name}: ").strip()
        if value:
            filled[key] = value
            logs.append({"sequential_fill": {key: value}})
    
    return filled

def ask_grouped_boolean_fields(grouped_booleans: dict, logs: list):
    """Ask boolean groups with multi-select, store as true/false"""
    filled = {}
    
    print("\n✅ Now let's select some categories:\n")
    
    for group_name, fields in grouped_booleans.items():
        print(f"\n--- {group_name} ---")
        options = list(fields)
        
        # Display options
        for i, key in enumerate(options, start=1):
            # Get readable name from path (second-to-last part before .value)
            path_parts = key.split(".")
            if len(path_parts) >= 2:
                opt_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
            else:
                opt_name = key.replace("_", " ").title()
            print(f"{i}. {opt_name}")
        
        # Get user selection
        while True:
            choice = input("Select one or multiple (comma-separated, e.g., 1,3): ").strip()
            try:
                if not choice:  # Allow empty selection
                    indices = []
                    break
                indices = [int(i) for i in choice.split(",") if i.strip()]
                if all(1 <= idx <= len(options) for idx in indices):
                    break
                else:
                    print("❌ Invalid input. Try again.")
            except ValueError:
                print("❌ Please enter numbers separated by commas.")
        
        # Store as true/false (ONLY for selected options, rest stay as is)
        for i, key in enumerate(options, start=1):
            filled[key] = (i in indices)
            logs.append({"boolean_selection": {key: filled[key]}})
    
    return filled

# ------------------- Main flow -------------------
def main():
    print("🌟 Welcome to Smart Form Assistant\n")
    
    # Setup
    session_folder = create_session_folder()
    live_fill_file = os.path.join(session_folder, "live_fill.json")
    log_file = os.path.join(session_folder, "log.json")
    
    form_keys = load_json(FORM_KEYS_FILE)
    mandatory_master = load_json(MANDATORY_FILE)
    
    live_fill = form_keys.copy()
    save_json(live_fill_file, live_fill)
    
    logs = []
    memory = ConversationBufferWindowMemory(k=MEMORY_BUFFER_SIZE, return_messages=False)
    
    # ============ PHASE 1: Select Investor Type ============
    mandatory_data = mandatory_master.get("Type of Investors", {})
    investor_list = list(mandatory_data.keys())
    
    if not investor_list:
        print("❌ No investor types found. Exiting.")
        return
    
    print("Available Investor Types:")
    for idx, t in enumerate(investor_list, start=1):
        print(f"{idx}. {t}")
    
    choice = input("\nEnter Investor Type (number or name): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(investor_list):
        investor_type = investor_list[int(choice) - 1]
    else:
        investor_type = choice
    
    if investor_type not in mandatory_data:
        print("❌ Invalid type. Exiting.")
        return
    
    print(f"\n✅ Investor type selected: {investor_type}\n")
    logs.append({"investor_type": investor_type})
    
    # Flatten form_keys only
    live_fill_flat = flatten_dict(live_fill)
    
    # CRITICAL: Resolve mandatory field mappings (don't flatten mandatory first!)
    print("🔄 Resolving field mappings...")
    mandatory_flat = resolve_field_mapping(mandatory_data[investor_type], live_fill_flat)
    print(f"✅ Mapped {len(mandatory_flat)} mandatory fields\n")
    
    if not mandatory_flat:
        print("⚠️ Warning: No valid mandatory fields found after mapping!")
        print("Check that field IDs in mandatory.json match those in form_keys.json")
        # Show example of expected vs actual
        print("\nExample mandatory.json entry:")
        print('  "Name": "investorFullLegalName_ID"')
        print("\nExpected form_keys.json entry:")
        print('  "Details in Subscription Booklet.investorFullLegalName_ID.value": ""')
        return
    
    # ============ PHASE 2: Conversational Information Gathering ============
    print("💬 Tell me about yourself! Share any information in your own words.\n")
    
    conversation_active = True
    
    while conversation_active:
        user_input = input("You: ").strip()
        
        if not user_input:
            continue
        
        # Save to memory
        memory.save_context({"input": user_input}, {"output": ""})
        
        # Extract using LLM + fallback
        chat_history = memory.load_memory_variables({}).get('history', '')
        
        extracted = llm_extract(user_input, chat_history, live_fill_flat)
        if not extracted:
            extracted = fallback_extract(user_input, live_fill_flat)
            logs.append({"extraction_method": "fallback", "result": extracted})
        else:
            logs.append({"extraction_method": "llm", "result": extracted})
        
        # Update live_fill
        if extracted:
            deep_update(live_fill_flat, extracted)
            save_json(live_fill_file, unflatten_dict(live_fill_flat))
            save_json(log_file, logs)
        
        # Generate natural follow-up
        missing = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
        followup = generate_natural_followup(extracted or {}, len(missing), chat_history)
        
        print(f"\n💬 {followup}")
        memory.save_context({"input": ""}, {"output": followup})
        
        continue_input = input("→ ").strip().lower()
        
        # Check if user wants to continue
        if continue_input in ["no", "n", "nope", "done", "that's all", "nothing", "nah", "finish"]:
            conversation_active = False
            print("\n✅ Great! Let me gather a few more details.\n")
        elif continue_input in ["yes", "y", "yeah", "sure", "yep", "ok", "okay", "more"]:
            print("\n💬 Go ahead:\n")
        else:
            # Treat as more information and loop again
            print()
    
    # ============ PHASE 3: Ask Mandatory Fields One-by-One ============
    missing_mandatory = get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
    
    if missing_mandatory:
        # Separate text fields and boolean groups
        text_fields, grouped_booleans = classify_mandatory_fields(missing_mandatory)
        
        # Ask text fields sequentially
        if text_fields:
            filled_text = ask_text_fields_sequential(text_fields, live_fill_flat, logs, live_fill_flat)
            deep_update(live_fill_flat, filled_text)
            save_json(live_fill_file, unflatten_dict(live_fill_flat))
            save_json(log_file, logs)
        
        # Ask boolean grouped fields - get ALL fields in each group, not just missing ones
        if grouped_booleans:
            # Rebuild grouped_booleans with ALL fields in each group
            complete_grouped_booleans = defaultdict(list)
            for group_name in grouped_booleans.keys():
                complete_grouped_booleans[group_name] = get_all_boolean_fields_in_group(
                    group_name, mandatory_flat, live_fill_flat
                )
            
            filled_booleans = ask_grouped_boolean_fields(complete_grouped_booleans, logs)
            deep_update(live_fill_flat, filled_booleans)
            save_json(live_fill_file, unflatten_dict(live_fill_flat))
            save_json(log_file, logs)
    
    print("\n✅ All mandatory fields filled!")
    
    # ============ PHASE 4: Optional Fields ============
    remaining_optional = get_remaining_optional_keys(live_fill_flat, mandatory_flat)
    
    if remaining_optional:
        opt_choice = input(f"\n🤔 There are {len(remaining_optional)} optional fields. Fill them? (yes/no): ").strip().lower()
        
        if opt_choice in ["yes", "y"]:
            filled_opt = ask_text_fields_sequential(remaining_optional, live_fill_flat, logs, live_fill_flat)
            deep_update(live_fill_flat, filled_opt)
            save_json(live_fill_file, unflatten_dict(live_fill_flat))
            save_json(log_file, logs)
    
    # ============ PHASE 5: Summary ============
    print("\n🎉 Form completed successfully!\n")
    print(f"📁 Session folder: {session_folder}")
    print(f"📄 Live JSON: {live_fill_file}")
    print(f"📝 Log file: {log_file}")
    print("\n✅ All data saved. Thank you!")

if __name__ == "__main__":
    main()