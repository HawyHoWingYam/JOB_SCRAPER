import pandas as pd
import io
import numpy as np # Needed for handling potential NaN values if columns have mixed types
import json # For formatting JSON examples

# --- Create buffer to hold excel data ---
excel_buffer = io.BytesIO()

# --- Sheet 1: Overview ---
overview_data = {
    'Property': [
        'API Name', 'Version', 'Description',
        'Base URL (NetSuite -> VM)', 'Base URL (VM -> NetSuite)',
        'Authentication (NetSuite -> VM)', 'Authentication (VM -> NetSuite)',
        'NetSuite Role Required', 'Contact Email', 'Last Updated', 'Status',
        'Data Format', 'Identifier Mapping (Locations)', 'Identifier Mapping (Items)',
        'Identifier Mapping (Item Subclass)', 'Identifier Mapping (Adj. Reason)',
        'API Versioning Strategy', 'Timezone Context (NetSuite Adj.)'
    ],
    'Value': [
        'Vending Machine Integration API', '1.2', # Updated Version
        'API for integrating NetSuite with Vending Machines for inventory sync and adjustments.',
        '[TBD_VM_BASE_URL]', '[TBD_NETSUITE_BASE_URL]',
        '[TBD_VM_AUTH_METHOD]', 'OAuth 1.0a or OAuth 2.0',
        'System Integration', 'api-support@yourcompany.com', pd.Timestamp.now().strftime('%Y-%m-%d'),
        'Development',
        'JSON (application/json)', 'VM Location Name maps to NetSuite Location Name.',
        'VM Item SKU maps to NetSuite Item Name/Number.',
        'VM Item Subclass Name maps to NetSuite Custom Field (Name/Text).',
        'VM Adjustment Reason Name maps to NetSuite Custom List/Record (Name/Text).',
        'URL Path Versioning (e.g., /v1/, /v2/)',
        'Hong Kong Time (UTC+8)'
    ],
    'Description': [
        'Official name of the API.', 'Current specification version.', 'High-level purpose.',
        'Base URL provided by VM Vendor.', 'Base URL for NS RESTlets/Suitelets.',
        'Method NS uses to auth with VM API (TBD).', 'Method VM uses to auth with NS API (OAuth recommended).',
        'NetSuite role for integration token/user.', 'Point of contact.', 'Date this specification was last modified.',
        'Current lifecycle status.',
        'Standard data format for request/response bodies.', 'How locations are identified between systems.',
        'How items are identified between systems (SKU primary).',
        'How item subclasses are identified (Name/Text value used in API).',
        'How adjustment reasons are identified (Name/Text value used in API, must match predefined list).',
        'Strategy for handling future API changes.',
        'NetSuite Inventory Adjustments will be created ensuring the date reflects HKT.'
    ]
}
df_overview = pd.DataFrame(overview_data)

# --- Sheet 2: Endpoints Summary ---
endpoints_summary_data = {
    'Endpoint Path (Template)': [
        '/v1/vm/locations/{location_id}/items',
        '/v1/vm/locations/{location_id}/inventory',
        '/v1/netsuite/items',
        '/v1/netsuite/inventory',
        '/v1/netsuite/adjustments',
        '/v1/netsuite/bulk/inventory' # Updated/Confirmed Bulk Endpoint
    ],
    'Method': ['GET', 'GET', 'GET', 'GET', 'POST', 'POST'], # Updated Bulk Method
    'System Providing API': ['Vending Machine', 'Vending Machine', 'NetSuite', 'NetSuite', 'NetSuite', 'NetSuite'],
    'Summary': [
        'Get items selling in VM (no quantity)',
        'Get items selling in VM (with quantity)',
        'Get available items from NetSuite (no quantity)',
        'Get available items from NetSuite (with quantity)',
        'Post inventory adjustment from VM to NetSuite (Async)',
        'Get inventory for multiple locations (Bulk)' # Updated Summary
    ],
    'Tags': ['Inventory', 'Inventory', 'Inventory', 'Inventory', 'Adjustments', 'Inventory']
}
df_endpoints_summary = pd.DataFrame(endpoints_summary_data)


# --- Sheet 4: Data Models (Schemas) ---
schemas_list = []

# Helper to add schema rows
def add_schema(model_name, field_name, data_type, required, description, constraints=''):
    schemas_list.append({
        'Model Name': model_name, 'Field Name': field_name, 'Data Type': data_type,
        'Required': required, 'Description': description, 'Example / Constraints': constraints
    })

# ErrorDetail
add_schema('ErrorDetail', 'errorCode', 'string', 'Yes', 'Machine-readable error code.', 'See Error Codes table in Spec Doc Section 8.')
add_schema('ErrorDetail', 'message', 'string', 'Yes', 'Human-readable error message.', 'e.g., Item SKU "SKU999" not found.')
add_schema('ErrorDetail', 'details', 'string', 'No', 'Optional additional context or technical details.', 'e.g., Check item master configuration.')

# --- NS -> VM Schemas ---
add_schema('VmItemDetail', 'item_name', 'string', 'Yes', 'Name of the item in VM.')
add_schema('VmItemDetail', 'item_sku', 'string', 'Yes', 'SKU of the item in VM.')
add_schema('VmItemDetail', 'base_unit', 'string', 'Yes', 'Base unit of measure (e.g., smallest sellable unit).', '"can"')
add_schema('VmItemDetail', 'stock_unit', 'string', 'Yes', 'Stocking/Selling unit in the VM (may differ from base_unit).', '"pack"')

add_schema('VmItemInventoryDetail', 'item_name', 'string', 'Yes', 'Name of the item.')
add_schema('VmItemInventoryDetail', 'item_sku', 'string', 'Yes', 'SKU of the item.')
add_schema('VmItemInventoryDetail', 'base_quantity', 'number', 'No', '(Informational) Number of base units per stock unit. TBD if VM provides.', '12')
add_schema('VmItemInventoryDetail', 'base_unit', 'string', 'Yes', 'Base unit of measure.', '"can"')
add_schema('VmItemInventoryDetail', 'stock_quantity', 'number', 'Yes', 'Current quantity in VM, in stock_unit. **Can be decimal**.', '3.5')
add_schema('VmItemInventoryDetail', 'stock_unit', 'string', 'Yes', 'Stocking/Selling unit in VM.', '"pack"')

add_schema('VmLocationDataBase', 'timestamp', 'integer', 'Yes', 'Unix timestamp (milliseconds) of data snapshot for logging.', '1745609160000')
add_schema('VmLocationDataBase', 'date', 'string (date)', 'Yes', 'Business date of snapshot (YYYY-MM-DD).', '"2025-04-25"')
add_schema('VmLocationDataBase', 'location', 'string', 'Yes', 'Identifier/Name of the vending machine location.', '"TGR"')

add_schema('VmLocationItemsResponse', '*(inherits)*', 'VmLocationDataBase', 'Yes', 'Base fields for location snapshot.')
add_schema('VmLocationItemsResponse', 'items', 'Array<VmItemDetail>', 'Yes', 'List of items available (no quantity).')

add_schema('VmLocationInventoryResponse', '*(inherits)*', 'VmLocationDataBase', 'Yes', 'Base fields for location snapshot.')
add_schema('VmLocationInventoryResponse', 'items', 'Array<VmItemInventoryDetail>', 'Yes', 'List of items and quantities.')


# --- VM -> NS Schemas ---
add_schema('NsItemDetail', 'item_name', 'string', 'Yes', 'Item Name from NetSuite.')
add_schema('NsItemDetail', 'item_sku', 'string', 'Yes', 'Item SKU (Name/Number) from NetSuite.')
add_schema('NsItemDetail', 'base_unit', 'string', 'Yes', 'Base Unit from NetSuite Item record.')
add_schema('NsItemDetail', 'stock_unit', 'string', 'No', 'Stock Unit from NetSuite Item record (if applicable).')

add_schema('NsItemInventoryDetail', 'item_name', 'string', 'Yes', 'Item Name from NetSuite.')
add_schema('NsItemInventoryDetail', 'item_sku', 'string', 'Yes', 'Item SKU (Name/Number) from NetSuite.')
add_schema('NsItemInventoryDetail', 'base_unit', 'string', 'Yes', 'Base Unit from NetSuite Item record.')
add_schema('NsItemInventoryDetail', 'stock_unit', 'string', 'No', 'Stock Unit from NetSuite Item record (if applicable).')
add_schema('NsItemInventoryDetail', 'qty_on_hand', 'number', 'Yes', 'Quantity On Hand for the item/location in NetSuite.')

add_schema('NsLocationDataBase', 'location', 'string', 'Yes', 'NetSuite Location Name.', '"TGR"')
add_schema('NsLocationDataBase', 'status', 'string', 'Yes', 'Indicates success/error for this location entry.', '"success", "error"')
add_schema('NsLocationDataBase', 'error', 'ErrorDetail', 'No', 'Included only if status is "error".')

add_schema('NsLocationItemData', '*(inherits)*', 'NsLocationDataBase', 'Yes', 'Base fields + status/error.')
add_schema('NsLocationItemData', 'items', 'Array<NsItemDetail>', 'Yes', 'List of items (no quantity). Empty if status is "error".')

add_schema('NsLocationInventoryData', '*(inherits)*', 'NsLocationDataBase', 'Yes', 'Base fields + status/error.')
add_schema('NsLocationInventoryData', 'items', 'Array<NsItemInventoryDetail>', 'Yes', 'List of items and quantities. Empty if status is "error".')

add_schema('NsResponseBase', 'timestamp', 'integer', 'Yes', 'Unix timestamp (milliseconds) when data generated by NetSuite.', '1745609160000')
add_schema('NsResponseBase', 'date', 'string (date)', 'Yes', 'Business date data corresponds to (YYYY-MM-DD).', '"2025-04-25"')

add_schema('NsLocationItemsResponse', '*(inherits)*', 'NsResponseBase', 'Yes', 'Base timestamp/date fields.')
add_schema('NsLocationItemsResponse', 'locations', 'Array<NsLocationItemData>', 'Yes', 'List of locations and their item details/status.')

add_schema('NsLocationInventoryResponse', '*(inherits)*', 'NsResponseBase', 'Yes', 'Base timestamp/date fields.')
add_schema('NsLocationInventoryResponse', 'locations', 'Array<NsLocationInventoryData>', 'Yes', 'List of locations and their inventory details/status.')

# Bulk Inventory Request (VM -> NS)
add_schema('NsBulkInventoryRequest', 'locations', 'Array<string>', 'Yes', 'List of NetSuite Location Names to query.', '["TGR", "IFC"]')
add_schema('NsBulkInventoryRequest', 'item_subclass', 'Array<string>', 'No', 'List of item subclass Name/Text values to filter by.', '["Drinks", "Snacks"]')

# Adjustment POST (VM -> NS)
add_schema('AdjustmentItemInput', 'item_sku', 'string', 'Yes', 'SKU of the item being adjusted. Must exist in NetSuite.', '"SKU001"')
add_schema('AdjustmentItemInput', 'adjust_to_qty', 'number', 'Yes', 'The final, absolute quantity counted in the VM for this item.', '15')

add_schema('AdjustmentRequest', 'vmTransactionId', 'string', 'Yes', 'Unique transaction ID from VM for idempotency. Max Length: TBD (e.g., 255).', '"VMADJ_TGR_20250425_12345"')
add_schema('AdjustmentRequest', 'location', 'string', 'Yes', 'NetSuite Location Name where adjustment occurred.', '"TGR"')
add_schema('AdjustmentRequest', 'date', 'string (date)', 'Yes', 'Date adjustment occurred (YYYY-MM-DD). Used for NS transaction date.', '"2025-04-25"')
add_schema('AdjustmentRequest', 'adjustment_reason', 'string', 'Yes', 'Name/Text value of the reason. Must match predefined list. List TBD.', '"Stock Take"')
add_schema('AdjustmentRequest', 'items', 'Array<AdjustmentItemInput>', 'Yes', 'List of items and final quantities. Max items TBD (e.g., 500).')

# Adjustment Response (NS -> VM)
add_schema('AsyncConfirmation', 'message', 'string', 'Yes', 'Human-readable confirmation message.', '"Adjustment request received and queued for processing."')
add_schema('AsyncConfirmation', 'vmTransactionId', 'string', 'Yes', 'The unique ID from the original request for correlation.', '"VMADJ_TGR_20250425_12345"')
add_schema('AsyncConfirmation', 'status', 'string', 'Yes', 'Indicates the immediate outcome of the queueing attempt.', '"QUEUED"')
add_schema('AsyncConfirmation', 'netsuiteProcessingId', 'string', 'No', 'Optional: NetSuite internal ID for tracking the queued job.', '"TASK_ID_12345"')


df_schemas = pd.DataFrame(schemas_list)
# Replace NaN with empty string for cleaner Excel output
df_schemas.fillna('', inplace=True)


# --- Sheet 3: Endpoint Details ---
details_columns = [
    'Path', 'Method', 'System Providing API', 'Summary', 'Description', 'Tags',
    'Path Parameters', 'Query Parameters', 'Request Headers',
    'Request Body (Content-Type)', 'Request Body Schema/Structure', 'Request Body Example',
    'Responses (Success)', 'Responses (Error)'
]
endpoint_details_list = []

# Helper function to format JSON examples nicely
def format_json_example(data):
    if data:
        try:
            # Use dumps for pretty printing within the cell string
            return f"```json\n{json.dumps(data, indent=2)}\n```"
        except TypeError:
            return str(data) # Fallback for non-serializable data
    return '*(None)*'

def add_details(path, method, system, summary, description, tags, path_params, query_params, req_headers, req_body_type, req_body_schema, req_body_example_dict, resp_success, resp_error):
     endpoint_details_list.append({
        'Path': path, 'Method': method, 'System Providing API': system,
        'Summary': summary, 'Description': description, 'Tags': tags,
        'Path Parameters': path_params if path_params else '*(None)*',
        'Query Parameters': query_params if query_params else '*(None)*',
        'Request Headers': req_headers if req_headers else '*(Standard)*',
        'Request Body (Content-Type)': req_body_type if req_body_type else '*(None)*',
        'Request Body Schema/Structure': f'`{req_body_schema}`' if req_body_schema else '*(None)*',
        'Request Body Example': format_json_example(req_body_example_dict),
        'Responses (Success)': resp_success,
        'Responses (Error)': resp_error
    })

# Endpoint 1: GET /v1/vm/locations/{location_id}/items
add_details(
    path='/v1/vm/locations/{location_id}/items', method='GET', system='Vending Machine',
    summary='Get items selling in VM (no quantity)',
    description='Retrieves items configured in a specific VM location (no quantity). Called by NetSuite.',
    tags='Inventory',
    path_params='`location_id` (string, required): VM Location Name.',
    query_params=None,
    req_headers='`Accept: application/json`\n`Authorization: (TBD by VM Vendor)`',
    req_body_type=None, req_body_schema=None, req_body_example_dict=None,
    resp_success='`200 OK:` Body: `VmLocationItemsResponse`',
    resp_error=('`401 Unauthorized`\n`403 Forbidden`\n`404 Not Found` (VM Loc)\n`429 Too Many Requests`\n`500 Internal Server Error`\n'
                '`503 Service Unavailable` / `504 Gateway Timeout` (If NS call fails)')
)

# Endpoint 2: GET /v1/vm/locations/{location_id}/inventory
add_details(
    path='/v1/vm/locations/{location_id}/inventory', method='GET', system='Vending Machine',
    summary='Get items selling in VM (with quantity)',
    description='Retrieves items and current stock quantities (can be decimal) for a specific VM location. Called by NetSuite.',
    tags='Inventory',
    path_params='`location_id` (string, required): VM Location Name.',
    query_params=None,
    req_headers='`Accept: application/json`\n`Authorization: (TBD by VM Vendor)`',
    req_body_type=None, req_body_schema=None, req_body_example_dict=None,
    resp_success='`200 OK:` Body: `VmLocationInventoryResponse`',
    resp_error=('`401 Unauthorized`\n`403 Forbidden`\n`404 Not Found` (VM Loc)\n`429 Too Many Requests`\n`500 Internal Server Error`\n'
                '`503 Service Unavailable` / `504 Gateway Timeout` (If NS call fails)')
)

# Endpoint 3: GET /v1/netsuite/items
add_details(
    path='/v1/netsuite/items', method='GET', system='NetSuite',
    summary='Get available items from NetSuite (no quantity)',
    description='Retrieves available items from NetSuite, filtered by location(s) and optional subclass name. Uses location exclusion list. Called by VM.',
    tags='Inventory',
    path_params=None,
    query_params=('`location` (string, required): NetSuite Location Name(s). Repeat parameter for multiple.\n'
                  '`item_subclass` (string, optional): Item Subclass Name/Text. Repeat parameter for multiple.'),
    req_headers='`Accept: application/json`\n`Authorization: <OAuth Header>`',
    req_body_type=None, req_body_schema=None, req_body_example_dict=None,
    resp_success='`207 Multi-Status:` (Recommended) Body: `NsLocationItemsResponse`. Indicates success/error per location (See Sec 7 Error Handling Option A).',
    resp_error=('`400 Bad Request` (Missing location param)\n`401 Unauthorized`\n`403 Forbidden`\n`429 Too Many Requests`\n`500 Internal Server Error`\n'
               '(Note: Location/Subclass Not Found errors are reported within the `207` response body)')
)

# Endpoint 4: GET /v1/netsuite/inventory
add_details(
    path='/v1/netsuite/inventory', method='GET', system='NetSuite',
    summary='Get available items from NetSuite (with quantity)',
    description='Retrieves available items and Quantity On Hand from NetSuite, filtered by location(s) and optional subclass name. Uses location exclusion list. Called by VM.',
    tags='Inventory',
    path_params=None,
    query_params=('`location` (string, required): NetSuite Location Name(s). Repeat parameter for multiple.\n'
                  '`item_subclass` (string, optional): Item Subclass Name/Text. Repeat parameter for multiple.'),
    req_headers='`Accept: application/json`\n`Authorization: <OAuth Header>`',
    req_body_type=None, req_body_schema=None, req_body_example_dict=None,
    resp_success='`207 Multi-Status:` (Recommended) Body: `NsLocationInventoryResponse`. Indicates success/error per location (See Sec 7 Error Handling Option A).',
    resp_error=('`400 Bad Request` (Missing location param)\n`401 Unauthorized`\n`403 Forbidden`\n`429 Too Many Requests`\n`500 Internal Server Error`\n'
               '(Note: Location/Subclass Not Found errors are reported within the `207` response body)')
)

# Endpoint 5: POST /v1/netsuite/adjustments
adjustment_request_example_dict = {
  "vmTransactionId": "VMADJ_TGR_20250425_12345",
  "location": "TGR",
  "date": "2025-04-25",
  "adjustment_reason": "Stock Take", # Must match predefined list
  "items": [
    { "item_sku": "SKU001", "adjust_to_qty": 12 },
    { "item_sku": "SKU002", "adjust_to_qty": 5 }
  ]
}
add_details(
    path='/v1/netsuite/adjustments', method='POST', system='NetSuite',
    summary='Post inventory adjustment from VM to NetSuite (Async)',
    description=('Submits inventory adjustment data (final counts) from VM. Validates (incl. reason), queues for async processing (creates NS Inventory Adjustment later), and returns `202 Accepted`. Uses `vmTransactionId` for idempotency.'),
    tags='Adjustments',
    path_params=None, query_params=None,
    req_headers='`Content-Type: application/json`\n`Accept: application/json`\n`Authorization: <OAuth Header>`',
    req_body_type='application/json', req_body_schema='AdjustmentRequest', req_body_example_dict=adjustment_request_example_dict,
    resp_success='`202 Accepted:` Body: `AsyncConfirmation`. Request queued successfully.',
    resp_error=('`400 Bad Request` (Invalid Body/Data/Reason/SKU/Loc)\n`401 Unauthorized`\n`403 Forbidden`\n`409 Conflict` (Duplicate vmTransactionId)\n`429 Too Many Requests`\n`500 Internal Server Error` (Validation/Queueing Error)')
)

# Endpoint 6: POST /v1/netsuite/bulk/inventory
bulk_request_example_dict = {
  "locations": ["TGR", "IFC", "OTHERLOC"],
  "item_subclass": ["Drinks", "Snacks"]
}
add_details(
    path='/v1/netsuite/bulk/inventory', method='POST', system='NetSuite',
    summary='Get inventory for multiple locations (Bulk)',
    description='Retrieves available items and Quantity On Hand from NetSuite for a list of locations. Allows filtering by item subclass name. Called by VM.',
    tags='Inventory',
    path_params=None, query_params=None,
    req_headers='`Content-Type: application/json`\n`Accept: application/json`\n`Authorization: <OAuth Header>`',
    req_body_type='application/json', req_body_schema='NsBulkInventoryRequest', req_body_example_dict=bulk_request_example_dict,
    resp_success='`207 Multi-Status:` (Recommended) Body: `NsLocationInventoryResponse`. Indicates success/error per location (See Sec 7 Error Handling Option A).',
    resp_error=('`400 Bad Request` (Invalid Body/Missing Locations)\n`401 Unauthorized`\n`403 Forbidden`\n`429 Too Many Requests`\n`500 Internal Server Error`\n'
                '(Note: Location/Subclass Not Found errors reported within `207` response body)')
)


# Convert list to DataFrame and ensure column order
df_endpoint_details = pd.DataFrame(endpoint_details_list, columns=details_columns)
# Replace NaN with empty string for cleaner Excel output
df_endpoint_details.fillna('', inplace=True)

# --- Write to Excel ---
output_file_name = "Updated_VM_API_Spec_v1.2.xlsx"
try:
    # Use xlsxwriter engine for potentially better formatting control if needed later
    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
        df_overview.to_excel(writer, sheet_name='Overview', index=False)
        df_endpoints_summary.to_excel(writer, sheet_name='Endpoints Summary', index=False)
        df_endpoint_details.to_excel(writer, sheet_name='Endpoint Details', index=False)
        df_schemas.to_excel(writer, sheet_name='Data Models (Schemas)', index=False)

        # Auto-adjust column widths using xlsxwriter
        workbook = writer.book
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            df_temp = None
            if sheet_name == 'Overview': df_temp = df_overview
            elif sheet_name == 'Endpoints Summary': df_temp = df_endpoints_summary
            elif sheet_name == 'Endpoint Details': df_temp = df_endpoint_details
            elif sheet_name == 'Data Models (Schemas)': df_temp = df_schemas

            if df_temp is not None:
              for idx, col in enumerate(df_temp.columns):
                  series = df_temp[col].astype(str)
                  # Calculate max length considering header and data, handle multi-line examples
                  max_len = max((series.map(lambda x: len(x.split('\n')[0])).max(), len(str(col)))) + 1
                  # Limit max width
                  max_len = min(max_len, 70)
                  worksheet.set_column(idx, idx, max_len)

    # Save buffer to a file
    with open(output_file_name, 'wb') as f:
        f.write(excel_buffer.getvalue())
    print(f"Successfully created updated API specification Excel file: {output_file_name}")

except Exception as e:
    print(f"Error creating Excel file: {e}")
    # Fallback or handle error appropriately

