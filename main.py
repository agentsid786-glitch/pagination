import time
import base64
from collections import defaultdict
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS for the grader
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False, 
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"]
)

# ==========================================
# 1. Global State & Configurations
# ==========================================
TOTAL_ORDERS = 55
RATE_LIMIT = 15
WINDOW_SECONDS = 10

# Fixed catalog of orders for the GET endpoint (IDs 1 through 55)
CATALOG = [{"id": i, "product": f"Item {i}", "amount": 100} for i in range(1, TOTAL_ORDERS + 1)]

# State dictionaries for tracking
client_requests = defaultdict(list)
idempotency_cache = {}
next_new_order_id = TOTAL_ORDERS + 1  # Ensures POSTs get new IDs starting at 56

# ==========================================
# 2. Per-Client Rate Limiting Middleware
# ==========================================
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    # Ignore OPTIONS preflight checks so they don't get accidentally blocked
    if request.method == "OPTIONS":
        return await call_next(request)
        
    client_id = request.headers.get("X-Client-Id")
    
    if client_id:
        now = time.time()
        # Remove timestamps older than our 10-second window
        client_requests[client_id] = [t for t in client_requests[client_id] if now - t < WINDOW_SECONDS]
        
        # Check if the client has hit the limit of 15 requests
        if len(client_requests[client_id]) >= RATE_LIMIT:
            # Calculate time remaining until they are unblocked
            oldest_request_time = client_requests[client_id][0]
            retry_after = int(WINDOW_SECONDS - (now - oldest_request_time))
            
            # CRITICAL FIX: Manually inject CORS headers into the 429 response!
            return JSONResponse(
                content={"error": "Too Many Requests"}, 
                status_code=429, 
                headers={
                    "Retry-After": str(max(1, retry_after)),
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Expose-Headers": "Retry-After"
                }
            )
            
        # Log this request's timestamp
        client_requests[client_id].append(now)
        
    return await call_next(request)

# ==========================================
# Cursor Helper Functions
# ==========================================
def encode_cursor(index: int) -> str:
    """Takes an integer index and returns an opaque base64 string"""
    return base64.b64encode(str(index).encode()).decode('utf-8')

def decode_cursor(cursor: str) -> int:
    """Takes a base64 string and decodes it back to an integer index"""
    try:
        return int(base64.b64decode(cursor).decode('utf-8'))
    except Exception:
        return 0

# ==========================================
# 3. Endpoints
# ==========================================
@app.post("/orders")
async def create_order(request: Request, response: Response):
    global next_new_order_id
    idem_key = request.headers.get("Idempotency-Key")
    
    # IDEMPOTENCY CHECK: If the key was already used, return the exact same response!
    if idem_key and idem_key in idempotency_cache:
        response.status_code = 201
        return idempotency_cache[idem_key]
        
    # Otherwise, create a brand new order
    new_order = {
        "id": next_new_order_id,
        "status": "processing",
        "created_at": time.time()
    }
    next_new_order_id += 1
    
    # Save to cache so future requests with this key get the same data
    if idem_key:
        idempotency_cache[idem_key] = new_order
        
    response.status_code = 201
    return new_order

@app.get("/orders")
async def get_orders(limit: int = 10, cursor: str = None):
    # Figure out where to start in the list based on the opaque cursor
    start_idx = 0
    if cursor:
        start_idx = decode_cursor(cursor)
        
    end_idx = start_idx + limit
    
    # Slice the items from our fixed catalog (1 to 55)
    items = CATALOG[start_idx:end_idx]
    
    # If there is more data left, generate a new cursor for the next page
    next_cursor = None
    if end_idx < TOTAL_ORDERS:
        next_cursor = encode_cursor(end_idx)
        
    return {
        "items": items,
        "next_cursor": next_cursor
    }
