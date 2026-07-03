import time
import base64
from collections import defaultdict
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS for the grader (Fixed credentials & exposed Retry-After header)
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
            
            return JSONResponse(
                content={"error": "Too Many Requests"}, 
                status_code=429, 
                headers={"Retry-After": str(max(1, retry_after))}
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
# =================
