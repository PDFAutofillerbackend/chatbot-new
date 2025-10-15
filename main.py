# main.py
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import json

# Import the updated smart_live_fill_final module
import live_fill_final as live_fill

app = FastAPI(title="Smart Form Assistant API - Unified Endpoint")

# =================== Models ===================
class UnifiedRequest(BaseModel):
    session_id: Optional[str] = None  # If None, creates new session
    investor_type: Optional[str] = None  # Required only for first call (session creation)
    action: str  # "chat", "fill_text", "fill_boolean", "get_status", "complete"
    user_input: Optional[str] = None  # For "chat" action
    field_key: Optional[str] = None  # For "fill_text" action
    field_value: Optional[str] = None  # For "fill_text" action
    group_name: Optional[str] = None  # For "fill_boolean" action
    selected_indices: Optional[List[int]] = None  # For "fill_boolean" action

# =================== Session Storage ===================
sessions = {}  # session_id -> session_data

class SessionData:
    def __init__(self, session_folder, investor_type, mandatory_flat, live_fill_flat, logs, memory):
        self.session_folder = session_folder
        self.investor_type = investor_type
        self.mandatory_flat = mandatory_flat
        self.live_fill_flat = live_fill_flat
        self.logs = logs
        self.memory = memory

# =================== Helper Functions ===================
def format_text_fields(text_fields: List[str]) -> List[Dict[str, str]]:
    """Format text fields with readable names"""
    formatted = []
    for key in text_fields:
        path_parts = key.split('.')
        if len(path_parts) >= 2:
            readable_name = path_parts[-2].replace("_", " ").replace("ID", "").strip().title()
        else:
            readable_name = key.replace("_", " ").title()
        
        formatted.append({
            "key": key,
            "display_name": readable_name
        })
    return formatted

def format_boolean_groups(grouped_booleans: Dict[str, List[str]]) -> Dict[str, List[Dict[str, Any]]]:
    """Format boolean groups with readable names"""
    formatted = {}
    for group_name, fields in grouped_booleans.items():
        options = []
        for i, key in enumerate(fields, start=1):
            path_parts = key.split(".")
            
            # Extract readable name
            opt_name = None
            for part in reversed(path_parts):
                clean_part = part.replace("_", " ").replace("ID", "").strip()
                if clean_part.lower() in ["value", "selected", "checkbox", "option"]:
                    continue
                if group_name and clean_part.lower() == group_name.lower():
                    continue
                opt_name = clean_part.title()
                break
            
            if not opt_name:
                opt_name = key.split(".")[-1].replace("_", " ").title()
            
            options.append({
                "index": i,
                "key": key,
                "display_name": opt_name
            })
        
        formatted[group_name] = options
    
    return formatted

def get_session_progress(session: SessionData) -> Dict[str, Any]:
    """Calculate session progress"""
    missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
    remaining_optional = live_fill.get_remaining_optional_keys(session.live_fill_flat, session.mandatory_flat)
    
    filled_mandatory = len(session.mandatory_flat) - len(missing_mandatory)
    filled_optional = len(session.live_fill_flat) - len(session.mandatory_flat) - len(remaining_optional)
    
    return {
        "mandatory_fields": {
            "total": len(session.mandatory_flat),
            "filled": filled_mandatory,
            "missing": len(missing_mandatory),
            "percentage": round((filled_mandatory / len(session.mandatory_flat)) * 100, 2) if session.mandatory_flat else 100
        },
        "optional_fields": {
            "total": len(session.live_fill_flat) - len(session.mandatory_flat),
            "filled": filled_optional,
            "remaining": len(remaining_optional)
        },
        "all_mandatory_filled": len(missing_mandatory) == 0
    }

# =================== Single Unified Endpoint ===================
@app.post("/process")
def process(req: UnifiedRequest):
    """
    Unified endpoint that handles all operations based on action type.
    
    Actions:
    - "init": Initialize new session (requires investor_type)
    - "chat": Conversational data extraction (requires session_id, user_input)
    - "fill_text": Fill single text field (requires session_id, field_key, field_value)
    - "fill_boolean": Fill boolean group (requires session_id, group_name, selected_indices)
    - "get_status": Get current session status (requires session_id)
    - "get_missing": Get all missing fields (requires session_id)
    - "complete": Finalize and return form data (requires session_id)
    """
    
    try:
        # =================== ACTION: INIT ===================
        if req.action == "init":
            if not req.investor_type:
                raise HTTPException(status_code=400, detail="investor_type is required for init action")
            
            # Load data
            form_keys = live_fill.load_json(live_fill.FORM_KEYS_FILE)
            mandatory_master = live_fill.load_json(live_fill.MANDATORY_FILE)
            
            # Validate investor type
            mandatory_data = mandatory_master.get("Type of Investors", {})
            if req.investor_type not in mandatory_data:
                available_types = list(mandatory_data.keys())
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid investor type. Available: {available_types}"
                )
            
            # Create session
            session_folder = live_fill.create_session_folder()
            session_id = os.path.basename(session_folder)
            
            # Setup files
            live_fill_file = os.path.join(session_folder, "live_fill.json")
            log_file = os.path.join(session_folder, "log.json")
            
            live_fill_data = form_keys.copy()
            live_fill.save_json(live_fill_file, live_fill_data)
            
            logs = [{"investor_type": req.investor_type}]
            live_fill.save_json(log_file, logs)
            
            # Flatten and resolve mappings
            live_fill_flat = live_fill.flatten_dict(live_fill_data)
            mandatory_flat = live_fill.resolve_field_mapping(mandatory_data[req.investor_type], live_fill_flat)
            
            # Initialize memory
            memory = live_fill.ConversationBufferWindowMemory(k=live_fill.MEMORY_BUFFER_SIZE, return_messages=False)
            
            # Store session
            sessions[session_id] = SessionData(
                session_folder=session_folder,
                investor_type=req.investor_type,
                mandatory_flat=mandatory_flat,
                live_fill_flat=live_fill_flat,
                logs=logs,
                memory=memory
            )
            
            # Get missing fields
            missing_mandatory = live_fill.get_missing_mandatory_keys(live_fill_flat, mandatory_flat)
            text_fields, grouped_booleans = live_fill.classify_mandatory_fields(missing_mandatory)
            
            progress = get_session_progress(sessions[session_id])
            
            return {
                "action": "init",
                "success": True,
                "session_id": session_id,
                "investor_type": req.investor_type,
                "progress": progress,
                "missing_fields": {
                    "text_fields": format_text_fields(text_fields[:10]),  # First 10
                    "boolean_groups": format_boolean_groups(grouped_booleans)
                },
                "message": "Session initialized successfully. You can now chat or fill fields."
            }
        
        # =================== ACTION: CHAT ===================
        elif req.action == "chat":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found. Initialize session first with action='init'")
            
            if not req.user_input:
                raise HTTPException(status_code=400, detail="user_input is required for chat action")
            
            session = sessions[req.session_id]
            
            # Save to memory
            session.memory.save_context({"input": req.user_input}, {"output": ""})
            
            # Extract data
            chat_history = session.memory.load_memory_variables({}).get('history', '')
            extracted = live_fill.llm_extract(req.user_input, chat_history, session.live_fill_flat)
            
            if not extracted:
                extracted = live_fill.fallback_extract(req.user_input, session.live_fill_flat)
                session.logs.append({"extraction_method": "fallback", "result": extracted})
            else:
                session.logs.append({"extraction_method": "llm", "result": extracted})
            
            # Update live_fill
            if extracted:
                live_fill.deep_update(session.live_fill_flat, extracted)
                live_fill_file = os.path.join(session.session_folder, "live_fill.json")
                live_fill.save_json(live_fill_file, live_fill.unflatten_dict(session.live_fill_flat))
                log_file = os.path.join(session.session_folder, "log.json")
                live_fill.save_json(log_file, session.logs)
            
            # Generate follow-up
            missing = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            followup = live_fill.generate_natural_followup(extracted or {}, len(missing), chat_history)
            session.memory.save_context({"input": ""}, {"output": followup})
            
            # Get remaining fields
            missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            text_fields, grouped_booleans = live_fill.classify_mandatory_fields(missing_mandatory)
            
            progress = get_session_progress(session)
            
            return {
                "action": "chat",
                "success": True,
                "session_id": req.session_id,
                "extracted_fields": extracted or {},
                "followup_message": followup,
                "progress": progress,
                "missing_fields": {
                    "text_fields": format_text_fields(text_fields[:10]),
                    "boolean_groups": format_boolean_groups(grouped_booleans)
                }
            }
        
        # =================== ACTION: FILL_TEXT ===================
        elif req.action == "fill_text":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            if not req.field_key or req.field_value is None:
                raise HTTPException(status_code=400, detail="field_key and field_value are required for fill_text action")
            
            session = sessions[req.session_id]
            
            # Validate field exists
            if req.field_key not in session.live_fill_flat:
                raise HTTPException(status_code=400, detail=f"Invalid field key: {req.field_key}")
            
            # Update field
            session.live_fill_flat[req.field_key] = req.field_value
            session.logs.append({"manual_fill": {req.field_key: req.field_value}})
            
            # Save
            live_fill_file = os.path.join(session.session_folder, "live_fill.json")
            live_fill.save_json(live_fill_file, live_fill.unflatten_dict(session.live_fill_flat))
            log_file = os.path.join(session.session_folder, "log.json")
            live_fill.save_json(log_file, session.logs)
            
            progress = get_session_progress(session)
            
            # Get remaining fields
            missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            text_fields, grouped_booleans = live_fill.classify_mandatory_fields(missing_mandatory)
            
            return {
                "action": "fill_text",
                "success": True,
                "session_id": req.session_id,
                "field_updated": req.field_key,
                "value": req.field_value,
                "progress": progress,
                "missing_fields": {
                    "text_fields": format_text_fields(text_fields[:10]),
                    "boolean_groups": format_boolean_groups(grouped_booleans)
                }
            }
        
        # =================== ACTION: FILL_BOOLEAN ===================
        elif req.action == "fill_boolean":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            if not req.group_name or req.selected_indices is None:
                raise HTTPException(status_code=400, detail="group_name and selected_indices are required for fill_boolean action")
            
            session = sessions[req.session_id]
            
            # Get fields in this group
            missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            _, grouped_booleans = live_fill.classify_mandatory_fields(missing_mandatory)
            
            if req.group_name not in grouped_booleans:
                available_groups = list(grouped_booleans.keys())
                raise HTTPException(
                    status_code=400, 
                    detail=f"Group not found. Available groups: {available_groups}"
                )
            
            fields = grouped_booleans[req.group_name]
            
            # Validate indices
            if req.selected_indices and not all(1 <= idx <= len(fields) for idx in req.selected_indices):
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid indices. Must be between 1 and {len(fields)}"
                )
            
            # Update fields
            for i, key in enumerate(fields, start=1):
                session.live_fill_flat[key] = (i in req.selected_indices)
                session.logs.append({"boolean_selection": {key: session.live_fill_flat[key]}})
            
            # Save
            live_fill_file = os.path.join(session.session_folder, "live_fill.json")
            live_fill.save_json(live_fill_file, live_fill.unflatten_dict(session.live_fill_flat))
            log_file = os.path.join(session.session_folder, "log.json")
            live_fill.save_json(log_file, session.logs)
            
            progress = get_session_progress(session)
            
            # Get remaining fields
            missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            text_fields, grouped_booleans_remaining = live_fill.classify_mandatory_fields(missing_mandatory)
            
            return {
                "action": "fill_boolean",
                "success": True,
                "session_id": req.session_id,
                "group_updated": req.group_name,
                "selected_count": len(req.selected_indices) if req.selected_indices else 0,
                "progress": progress,
                "missing_fields": {
                    "text_fields": format_text_fields(text_fields[:10]),
                    "boolean_groups": format_boolean_groups(grouped_booleans_remaining)
                }
            }
        
        # =================== ACTION: GET_STATUS ===================
        elif req.action == "get_status":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = sessions[req.session_id]
            progress = get_session_progress(session)
            
            return {
                "action": "get_status",
                "success": True,
                "session_id": req.session_id,
                "investor_type": session.investor_type,
                "session_folder": session.session_folder,
                "progress": progress
            }
        
        # =================== ACTION: GET_MISSING ===================
        elif req.action == "get_missing":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = sessions[req.session_id]
            
            missing_mandatory = live_fill.get_missing_mandatory_keys(session.live_fill_flat, session.mandatory_flat)
            text_fields, grouped_booleans = live_fill.classify_mandatory_fields(missing_mandatory)
            
            return {
                "action": "get_missing",
                "success": True,
                "session_id": req.session_id,
                "missing_count": len(missing_mandatory),
                "missing_fields": {
                    "text_fields": format_text_fields(text_fields),
                    "boolean_groups": format_boolean_groups(grouped_booleans)
                }
            }
        
        # =================== ACTION: COMPLETE ===================
        elif req.action == "complete":
            if not req.session_id or req.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = sessions[req.session_id]
            
            # Load final data
            live_fill_file = os.path.join(session.session_folder, "live_fill.json")
            live_data = live_fill.load_json(live_fill_file)
            
            progress = get_session_progress(session)
            
            return {
                "action": "complete",
                "success": True,
                "session_id": req.session_id,
                "investor_type": session.investor_type,
                "progress": progress,
                "form_data": live_data,
                "session_folder": session.session_folder,
                "message": "Form data retrieved successfully"
            }
        
        # =================== INVALID ACTION ===================
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid action: {req.action}. Valid actions: init, chat, fill_text, fill_boolean, get_status, get_missing, complete"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# =================== Additional Helper Endpoints ===================

@app.get("/available_investor_types")
def get_available_investor_types():
    """Get list of available investor types"""
    try:
        mandatory_master = live_fill.load_json(live_fill.MANDATORY_FILE)
        investor_types = list(mandatory_master.get("Type of Investors", {}).keys())
        
        return {
            "success": True,
            "investor_types": investor_types,
            "count": len(investor_types)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session from memory"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del sessions[session_id]
    
    return {
        "success": True,
        "session_id": session_id,
        "message": "Session deleted successfully"
    }


@app.get("/")
def root():
    """Health check and API info"""
    return {
        "service": "Smart Form Assistant API",
        "version": "1.0",
        "status": "running",
        "active_sessions": len(sessions),
        "endpoint": "/process",
        "actions": ["init", "chat", "fill_text", "fill_boolean", "get_status", "get_missing", "complete"]
    }