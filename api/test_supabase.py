from supabase import create_client, Client
import os


#supabase API Key
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

response = supabase.table("ap_areas").select("*").execute()
print(response)