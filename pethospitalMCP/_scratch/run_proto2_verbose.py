import uvicorn
import proto2_server as m

uvicorn.run(m.app, host="127.0.0.1", port=8903, log_level="info", access_log=True)
