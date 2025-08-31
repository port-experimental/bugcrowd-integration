import requests
from datetime import datetime, timedelta
import json

# ---- Config ----
BUGCROWD_API_TOKEN = "<YOUR_BUGCROWD_API_TOKEN>"  # Format: "identifier:secret_key" (from BugCrowd API Credentials page)
BUGCROWD_BASE_URL = "https://api.bugcrowd.com"

PORT_BASE_URL = "https://api.getport.io/v1"
PORT_CLIENT_ID = "<YOUR_PORT_CLIENT_ID>"
PORT_CLIENT_SECRET = "<YOUR_PORT_CLIENT_SECRET>"

# Blueprint IDs in Port
BP_BUGCROWD_PROGRAM = "bugcrowd_program"
BP_BUGCROWD_SUBMISSION = "bugcrowd_submission"

# Port authentication - no global variables needed

def bugcrowd_headers():
    """Get headers for BugCrowd API requests"""
    return {
        "Accept": "application/vnd.bugcrowd+json",
        "Authorization": f"Token {BUGCROWD_API_TOKEN}",
        "Bugcrowd-Version": "2025-04-23",  # Pin to latest API version
        "User-Agent": "Port-BugCrowd-Integration/1.0"
    }

def get_port_access_token():
    """Get a fresh access token from Port using client credentials"""
    print("🔐 Authenticating with Port...")
    auth_url = "https://api.getport.io/v1/auth/access_token"
    
    auth_data = {
        "clientId": PORT_CLIENT_ID,
        "clientSecret": PORT_CLIENT_SECRET
    }
    
    try:
        response = requests.post(auth_url, json=auth_data, timeout=30)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data.get("accessToken")
        
        if access_token:
            print("✅ Successfully authenticated with Port")
            return access_token
        else:
            print("❌ Failed to get access token from Port")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error authenticating with Port: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected authentication error: {e}")
        return None

def port_headers(access_token: str):
    """Get headers for Port API requests"""
    if not access_token:
        return None
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

# ---- Port Helpers ----
def upsert_entity(access_token: str, blueprint: str, identifier: str, title: str, properties: dict, relations: dict = None):
    body = {
        "identifier": identifier,
        "title": title,
        "properties": properties,
    }
    if relations:
        body["relations"] = relations

    headers = port_headers(access_token)
    if not headers:
        print(f"❌ Cannot upsert {blueprint}:{identifier} - no valid Port token")
        return None

    url = f"{PORT_BASE_URL}/blueprints/{blueprint}/entities?upsert=true"
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        print(f"✅ Upserted {blueprint}:{identifier}")
        return r.json()
    except Exception as e:
        print(f"❌ Failed to upsert {blueprint}:{identifier}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_details = e.response.json()
                print(f"  📋 Port validation errors: {error_details}")
            except:
                print(f"  📋 Raw response: {e.response.text}")
        return None

# ---- BugCrowd Fetchers ----
def get_bugcrowd_programs():
    """Get all programs from BugCrowd"""
    url = f"{BUGCROWD_BASE_URL}/programs"
    
    programs = []
    
    try:
        print(f"📥 Fetching programs...")
        
        # Try without pagination first to see if basic call works
        response = requests.get(url, headers=bugcrowd_headers(), timeout=30)
        response.raise_for_status()
        
        data = response.json()
        page_programs = data.get("data", [])
        
        if page_programs:
            programs.extend(page_programs)
            print(f"  ✅ Found {len(page_programs)} programs")
        else:
            print(f"  ℹ️ No programs found in response")
            
        # TODO: Handle pagination later if needed based on response structure
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching BugCrowd programs: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return []
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return []
    
    print(f"📊 Total programs fetched: {len(programs)}")
    return programs

def transform_program_to_port(program):
    """Transform BugCrowd program data to Port entity format"""
    attributes = program.get("attributes", {})
    
    # Extract basic properties
    identifier = program.get("id", "")
    title = attributes.get("name", f"Program {identifier}")
    
    properties = {
        "description": attributes.get("description", "")[:1000],  # Limit description length
        "state": attributes.get("state", "active"),
        "created_at": attributes.get("created_at"),
        "updated_at": attributes.get("updated_at"),
        "program_type": attributes.get("program_type", ""),
        "maximum_reward": attributes.get("maximum_reward", {}).get("cents", 0) if attributes.get("maximum_reward") else 0,
        "bugcrowd_url": f"https://bugcrowd.com/{attributes.get('code', identifier)}"
    }
    
    return identifier, title, properties

# ---- Submission Fetchers ----
def get_all_bugcrowd_submissions(days_back: int = 30):
    """Get submissions from all BugCrowd programs"""
    all_submissions = []
    
    # Get all programs first
    programs = get_bugcrowd_programs()
    
    for program in programs:
        program_id = program.get("id", "")
        program_name = program.get("attributes", {}).get("name", "Unknown")
        print(f"\n🔍 Fetching submissions for program: {program_name} ({program_id})")
        
        program_submissions = get_bugcrowd_submissions_for_program(program_id, days_back)
        
        # Add program context to each submission
        for submission in program_submissions:
            submission["_program_id"] = program_id
            submission["_program_name"] = program_name
            
        all_submissions.extend(program_submissions)
        
    return all_submissions

def get_bugcrowd_submissions_for_program(program_id: str, days_back: int = 30):
    """Get submissions from BugCrowd for a specific program"""
    since_date = (datetime.utcnow() - timedelta(days=days_back)).isoformat() + "Z"
    
    # Try the direct submissions endpoint with program filter instead
    url = f"{BUGCROWD_BASE_URL}/submissions"
    # Extract program code from the program data for the correct filter
    program_code = None
    programs = get_bugcrowd_programs()
    for prog in programs:
        if prog.get("id") == program_id:
            program_code = prog.get("attributes", {}).get("code", "")
            break
    
    if not program_code:
        print(f"⚠️ Could not find program code for {program_id}")
        return []
    
    params = {
        "filter[program]": program_code,
        "sort": "submitted-desc",  # Use BugCrowd's expected sort format
        "include": "researcher,target"  # Include related data to get names
    }
    
    submissions = []
    page = 1
    
    try:
        print(f"📥 Fetching submissions for program {program_id}...")
        
        response = requests.get(url, headers=bugcrowd_headers(), params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        page_submissions = data.get("data", [])
        included_data = data.get("included", [])
        
        if page_submissions:
            # Store included data with submissions for name resolution
            for submission in page_submissions:
                submission["_included_data"] = included_data
                
            submissions.extend(page_submissions)
            print(f"  ✅ Found {len(page_submissions)} submissions")
            if included_data:
                print(f"  ✅ Found {len(included_data)} included entities for name resolution")
        else:
            print(f"  ℹ️ No submissions found for this program")
            
        # TODO: Handle pagination later if needed
                
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching BugCrowd submissions: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return []
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return []
    
    print(f"📊 Total submissions fetched: {len(submissions)}")
    return submissions

def transform_submission_to_port(submission, program_id: str, included_data=None):
    """Transform BugCrowd submission data to Port entity format"""
    attributes = submission.get("attributes", {})
    relationships = submission.get("relationships", {})
    
    # Extract basic properties
    identifier = submission.get("id", "")
    title = attributes.get("title", f"Submission {identifier}")
    
    # Use BugCrowd values directly - convert severity to string
    raw_severity = attributes.get("severity")
    if raw_severity is not None:
        severity = str(raw_severity)
    else:
        severity = "5"  # Default to "5" (lowest priority) if None
    
    state = attributes.get("state", "new")    # String, default to new
    
    # Create a lookup for included data
    included_lookup = {}
    if included_data:
        for item in included_data:
            included_lookup[f"{item.get('type')}-{item.get('id')}"] = item
    
    # Extract researcher name from relationships and included data
    researcher_name = "Unknown"
    if "researcher" in relationships and relationships["researcher"].get("data"):
        researcher_data = relationships["researcher"]["data"]
        researcher_id = researcher_data.get("id")
        researcher_type = researcher_data.get("type")
        
        # Look up in included data for actual name
        lookup_key = f"{researcher_type}-{researcher_id}"
        if lookup_key in included_lookup:
            included_researcher = included_lookup[lookup_key]
            researcher_attrs = included_researcher.get("attributes", {})
            researcher_name = researcher_attrs.get("username") or researcher_attrs.get("name") or f"Researcher-{researcher_id}"
        else:
            researcher_name = f"Researcher-{researcher_id}"
    
    # Extract target info from relationships and included data
    target_name = ""
    if "target" in relationships and relationships["target"].get("data"):
        target_data = relationships["target"]["data"]
        target_id = target_data.get("id")
        target_type = target_data.get("type")
        
        # Look up in included data for actual name
        lookup_key = f"{target_type}-{target_id}"
        if lookup_key in included_lookup:
            included_target = included_lookup[lookup_key]
            target_attrs = included_target.get("attributes", {})
            target_name = target_attrs.get("name") or target_attrs.get("url") or f"Target-{target_id}"
        else:
            target_name = f"Target-{target_id}"
    
    properties = {
        "description": attributes.get("description", "")[:1000],  # Limit description length
        "severity": severity,
        "status": state,
        "submitted_at": attributes.get("submitted_at"),
        "researcher_name": researcher_name,
        "target": target_name,
        "bugcrowd_url": f"https://bugcrowd.com/submissions/{identifier}"
    }
    
    return identifier, title, properties, program_id

# Service mapping removed - can be added back later if needed

# ---- Main Sync ----
def main():
    print("🚀 Starting BugCrowd programs and submissions sync...")
    
    # Authenticate with Port first
    port_token = get_port_access_token()
    if not port_token:
        print("❌ Failed to authenticate with Port. Exiting.")
        return
    
    # Step 1: Fetch and create all programs
    print("\n📋 Step 1: Fetching BugCrowd programs...")
    programs = get_bugcrowd_programs()
    
    if not programs:
        print("❌ No programs found - check your BugCrowd configuration")
        return
    
    processed_programs = 0
    for program in programs:
        try:
            identifier, title, properties = transform_program_to_port(program)
            
            # Create program entity
            result = upsert_entity(
                port_token,
                BP_BUGCROWD_PROGRAM,
                identifier,
                title,
                properties
            )
            
            if result:
                processed_programs += 1
                
        except Exception as e:
            print(f"❌ Error processing program {program.get('id', 'unknown')}: {e}")
            continue
    
    print(f"✅ Programs sync completed! Processed {processed_programs} out of {len(programs)} programs.")
    
    # Step 2: Fetch and create submissions for all programs
    print("\n🐛 Step 2: Fetching BugCrowd submissions...")
    submissions = get_all_bugcrowd_submissions(days_back=30)
    
    if not submissions:
        print("❌ No submissions found")
        return
    
    print(f"\n🔄 Processing {len(submissions)} submissions...")
    
    processed_submissions = 0
    
    for submission in submissions:  # Process all submissions
        try:
            program_id = submission.get("_program_id", "")
            included_data = submission.get("_included_data", [])
            identifier, title, properties, program_relation = transform_submission_to_port(submission, program_id, included_data)
            


            # Build relations - only program relation now
            relations = {"program": program_relation}
            
            # Upsert submission entity to Port
            result = upsert_entity(
                port_token,
                BP_BUGCROWD_SUBMISSION, 
                identifier, 
                title,
                properties, 
                relations
            )
            
            if result:
                processed_submissions += 1
                
        except Exception as e:
            print(f"❌ Error processing submission {submission.get('id', 'unknown')}: {e}")
            continue
    
    print(f"\n🎉 Complete sync finished!")
    print(f"📊 Programs: {processed_programs}/{len(programs)}")
    print(f"🐛 Submissions: {processed_submissions}/{len(submissions)}")
    print(f"🌐 View your BugCrowd data in Port: {PORT_BASE_URL.replace('/v1', '')}")

if __name__ == "__main__":
    main()
