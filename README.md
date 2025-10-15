# 1️⃣ Flow Overview

**1. Session Initialization**:-

A unique session folder is created (chatbot_sessions/YYYYMMDD_HHMMSS_UUID/) for storing:

live_fill.json → holds the form keys + user-provided values.

log.json → stores conversation logs and extracted values.

**2. Load Data**

form_keys.json → full structure of fields that can be filled.

mandatory.json → subset of form_keys.json containing mandatory fields for each type of investor.

**3. Select Investor Type**

The chatbot lists all available investor types (A, B, C… or names).

User selects one.

The selected type determines which mandatory fields need to be filled.

**4. Free-text Input**

User can provide any information in natural language (NLP input).

OpenAI LLM is called to map the user input to the correct keys in live_fill.json.

Updates the live form with values extracted from the input.

User is repeatedly prompted:

"Do you want to add more information or finish now?" → yes/no

The loop continues until user says “no”.

**5. Mandatory Fields Completion**

After the free-text step, the chatbot checks which mandatory fields are still empty.

Prompts user to fill each missing mandatory key individually.

**6. Optional Fields Completion**

Remaining non-mandatory keys (empty) are considered optional.

User is asked if they want to fill optional fields.

Each optional key is prompted individually.

**7. Session Summary**

The chatbot prints a summary of all collected information.

live_fill.json and log.json are saved for the session.

**2️⃣ Example Run**

Assume:

form_keys.json contains:

{
  "Name": "",
  "Email": "",
  "Phone": "",
  "Address": {
    "Line1": "",
    "City": "",
    "State": "",
    "Zip": ""
  },
  "Investment Amount": "",
  "Share Class": ""
}

mandatory.json for Trade Booking (Initial Subs):

{
  "Type of Investors": {
    "Trade Booking (Initial Subs)": {
      "Name": "",
      "Email": "",
      "Investment Amount": ""
    }
  }
}

Session Start:

🌟 Welcome to Smart Form Assistant!

Available Investor Types:
A. Trade Booking (Initial Subs)
B. Individual
C. Partnership

User selects:

You: A

Free-text input step:

You: My name is Alice Johnson and my email is <alice@example.com>.

Chatbot calls OpenAI LLM to extract values:

{
  "Name": "Alice Johnson",
  "Email": "<alice@example.com>"
}

Updates live_fill.json.

Chatbot asks:

🤖 Would you like to add more information or finish now? (yes/no):

User types:

no

Mandatory fields check:

LLM extracted Name and Email.

Investment Amount is missing.

Chatbot prompts:

⚠️ Some mandatory fields are missing. Please provide them:

→ Investment Amount:

User inputs:

100000

Mandatory fields now complete.

Optional fields step:

Remaining optional fields: Phone, Address.Line1, Address.City, etc.

Chatbot asks:

🤖 Do you wish to fill optional fields as well? (yes/no):

User says yes.

Chatbot asks each optional key individually:

→ Phone:

→ Address Line1:

User can press Enter to skip.

Session Summary:

🎉 Session Complete! All information saved.

📝 Summary of collected information:
Name: Alice Johnson
Email: <alice@example.com>
Investment Amount: 100000
Phone:
Address.Line1:
Address.City:
...

live_fill.json is updated with all collected values.

log.json contains the user inputs and extracted values for auditing.

✅ Key Points

Free-text input is mapped via OpenAI to correct keys in live_fill.json.

Mandatory fields are checked locally, no LLM needed.

Optional fields are prompted if user wants to fill them.

Conversation and form data are session-based.

flatten_dict / unflatten_dict is used to handle nested JSON structures easily.
