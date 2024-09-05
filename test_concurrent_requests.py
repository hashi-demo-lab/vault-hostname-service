import requests
import threading
import json
import random
import time
import hvac

# URL of the microservice and Vault API
MICROSERVICE_URL = "http://localhost:32001/generate-name"
VAULT_URL = "https://vault-dc1.hashibank.com:443/v1/hostnaming/data/names"

# Vault configuration
ca_cert_path = '../sea-vault-demos/_setup/cert/kubernetes_ca.crt'
VAULT_TOKEN = "my_vault_token"
VAULT_CLIENT = hvac.Client(url="https://vault-dc1.hashibank.com:443", token=VAULT_TOKEN, verify=ca_cert_path)

# Define the applications, roles, and environments to be tested
applications = ["splunk", "nginx", "db"]
roles = ["web", "app", "db"]
environments = ["dev", "test", "prod"]

# Number of concurrent requests
NUM_REQUESTS = 500

# Store results for validation and grouping
generated_names = []
generated_names_lock = threading.Lock()
grouped_names = {}

# Function to send a POST request to the microservice
def generate_name_request(i):
    # Randomly select an application, role, and environment for each request
    application = random.choice(applications)
    role = random.choice(roles)
    environment = random.choice(environments)

    # Create the data payload
    data = {
        "application": application,
        "role": role,
        "environment": environment
    }

    try:
        # Send the POST request
        response = requests.post(MICROSERVICE_URL, headers={"Content-Type": "application/json"}, data=json.dumps(data))
        
        # Handle response
        if response.status_code == 200:
            result = response.json()
            unique_name = result["unique_name"]
            
            # Store the generated name
            with generated_names_lock:
                generated_names.append(unique_name)
                
                # Group the names by application, role, and environment
                if application not in grouped_names:
                    grouped_names[application] = {}
                if role not in grouped_names[application]:
                    grouped_names[application][role] = {}
                if environment not in grouped_names[application][role]:
                    grouped_names[application][role][environment] = []
                grouped_names[application][role][environment].append(unique_name)
                
            print(f"Request {i}: {response.status_code} - {result}")
        else:
            print(f"Request {i}: {response.status_code} - {response.text}")
    
    except Exception as e:
        print(f"Request {i} failed with exception: {e}")

# Function to run multiple threads for concurrency testing
def run_concurrent_requests(num_requests):
    threads = []
    start_time = time.time()

    # Create and start threads
    for i in range(num_requests):
        t = threading.Thread(target=generate_name_request, args=(i,))
        threads.append(t)
        t.start()

    # Wait for all threads to finish
    for t in threads:
        t.join()

    end_time = time.time()
    print(f"Completed {num_requests} requests in {end_time - start_time:.2f} seconds")

# Function to check uniqueness of generated names
def check_uniqueness(names):
    if len(names) == len(set(names)):
        print("All generated names are unique.")
    else:
        duplicates = [name for name in set(names) if names.count(name) > 1]
        print(f"Duplicate names found: {duplicates}")

# Function to validate names exist in Vault
def validate_names_in_vault(names):
    missing_in_vault = []
    for name in names:
        try:
            # Check if the name exists in Vault
            response = VAULT_CLIENT.secrets.kv.v2.read_secret_version(
                path=f"names/{name}",
                mount_point="hostnaming",
                raise_on_deleted_version=True  # Fix for deprecation warning
            )
            if response is None:
                missing_in_vault.append(name)
        except hvac.exceptions.InvalidPath:
            missing_in_vault.append(name)

    if missing_in_vault:
        print(f"Names missing in Vault: {missing_in_vault}")
    else:
        print("All generated names exist in Vault.")

# Function to print grouped names
def print_grouped_names(grouped_names):
    for application, roles in grouped_names.items():
        print(f"Application: {application}")
        for role, environments in roles.items():
            print(f"  Role: {role}")
            for environment, names in environments.items():
                print(f"    Environment: {environment}")
                print(f"      Names: {', '.join(names)}")

# Run the test with 500 concurrent requests
if __name__ == "__main__":
    run_concurrent_requests(NUM_REQUESTS)
    
    # Validate uniqueness of generated names
    check_uniqueness(generated_names)

    # Validate each generated name exists in Vault
    validate_names_in_vault(generated_names)

    # Print the grouped names by application, role, and environment
    print_grouped_names(grouped_names)
