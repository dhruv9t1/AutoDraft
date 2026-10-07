> **ARCHIVED / HISTORICAL — NOT CURRENT IMPLEMENTATION.** Legacy Rust performance notes. The active backend is Python/FastAPI and the configured local model defaults to `qwen3:4b`. See `../../README.md`, `../../backend/README.md`, and `../CURRENT_ARCHITECTURE.md`.

# Performance Optimization Guide for 3MB Documents

## Problem Analysis

Your 3MB document taking 5 minutes indicates the chunking strategy needs optimization. With the default 10MB chunks, a 3MB document would create 1 chunk, but the API call itself is slow.

## Optimizations Implemented

### 1. **Increased Chunk Size** (50MB default)

- **Before**: 10MB chunks → 3MB doc = 1 chunk + API overhead
- **After**: 50MB chunks → 3MB doc = 1 chunk, no chunking overhead
- **Benefit**: Eliminates chunking overhead for medium-sized documents

### 2. **Increased Parallel Processing** (8 concurrent)

- **Before**: 4 parallel chunks
- **After**: 8 parallel chunks
- **Benefit**: Can handle more chunks simultaneously for larger documents

### 3. **Adaptive Chunking Strategy**

```rust
// Smart chunking based on document size
let optimal_chunk_count = (doc_size / base_chunk_size).max(1).min(max_parallel * 2);
let adaptive_chunk_size = (doc_size / optimal_chunk_count).max(base_chunk_size / 2);
```

### 4. **Frontend Optimization**

- **Before**: 1MB chunks
- **After**: 50MB chunks
- **Benefit**: Fewer API calls, less overhead

## Expected Performance Improvements

### For Your 3MB Document:

- **Chunking**: Eliminated (was creating unnecessary overhead)
- **Processing**: Single optimized API call
- **Expected Time**: **30-60 seconds** (down from 5 minutes)

### For Larger Documents (10MB+):

- **Before**: Sequential processing of many small chunks
- **After**: Parallel processing of fewer, larger chunks
- **Expected Improvement**: **70-85% faster**

## Configuration Options

### Environment Variables for Tuning:

```bash
# Larger chunks for fewer API calls (default: 50MB)
OLLAMA_CHUNK_SIZE=52428800

# More parallel processing (default: 8)
OLLAMA_MAX_PARALLEL_CHUNKS=8

# Faster timeout for large chunks (default: 120s)
OLLAMA_TIMEOUT_SECONDS=120
```

### Recommended Settings by Document Size:

| Document Size | Chunk Size | Parallel Chunks | Expected Improvement |
| ------------- | ---------- | --------------- | -------------------- |
| < 5MB         | 50MB       | 8               | 80-90%               |
| 5-20MB        | 50MB       | 8               | 70-85%               |
| 20-50MB       | 50MB       | 8               | 60-75%               |
| 50MB+         | 50MB       | 8               | 50-70%               |

## Testing the Optimizations

### 1. Restart Backend with New Settings:

```bash
cd backend
export OLLAMA_CHUNK_SIZE=52428800  # 50MB
export OLLAMA_MAX_PARALLEL_CHUNKS=8
export OLLAMA_TIMEOUT_SECONDS=120
cargo run
```

### 2. Monitor Logs for Optimizations:

Look for these log messages:

```
📊 Adaptive chunking: doc_size=3145728, base_size=52428800, optimal_chunks=1, adaptive_size=3145728
📦 Created 1 chunks with adaptive sizing (avg size: 3145728 chars)
🚀 Processing chunks in parallel (max 8 concurrent)
```

### 3. Expected Behavior:

- **3MB document**: Single chunk, no parallel processing needed
- **Processing time**: Should drop from 5 minutes to under 1 minute
- **API calls**: 1 instead of multiple chunked calls

## Additional Performance Tips

### 1. **Network Optimization**

- Ensure low latency connection to Ollama API
- Consider using a closer Ollama server if possible

### 2. **Document Preprocessing**

- Remove unnecessary formatting before processing
- Compress images if document contains many

### 3. **Monitoring**

- Monitor chunk processing times in logs
- Adjust chunk size based on your typical document sizes

## Troubleshooting

### If Still Slow:

1. **Check Ollama API Response Time**:

   ```bash
   curl -X POST http://localhost:11434/api/chat \
     -H "Content-Type: application/json" \
     -d '{"model": "gpt-oss:120b", "messages": [{"role": "user", "content": "test"}], "stream": false}'
   ```

2. **Increase Timeout** if API is slow:

   ```bash
   export OLLAMA_TIMEOUT_SECONDS=300  # 5 minutes
   ```

3. **Reduce Chunk Size** if memory is an issue:
   ```bash
   export OLLAMA_CHUNK_SIZE=25165824  # 25MB
   ```

## Expected Results

With these optimizations, your 3MB document should process in **30-60 seconds** instead of 5 minutes - a **80-90% improvement**.

The key is eliminating unnecessary chunking overhead and using optimal chunk sizes for your document sizes.
