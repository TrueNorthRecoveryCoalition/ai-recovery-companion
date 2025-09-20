from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# Create FastAPI app
app = FastAPI(title="AI Recovery Companion")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AI Recovery Companion is running!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "AI Recovery Companion"}

@app.post("/chat")
async def chat():
    return {"response": "Chat functionality coming soon"}

@app.post("/send-sms")
async def send_sms():
    return {"status": "SMS functionality coming soon"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
