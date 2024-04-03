from fastapi import FastAPI
from typing import Union

app = FastAPI()
connection = pymysql.connect(
        host = dbinfo.db_host,
        user = dbinfo.db_username,
        passwd = dbinfo.db_password,
        db = dbinfo.db_name,
        port = dbinfo.db_port
    )

@app.get("/")
async def root():
    return {"msg" : "Hello World"}

@app.get("/home")
async def root():
    return {"msg" : "home"}

#  http://127.0.0.1:8000/items/5?q=somequery
@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}



#https://fastapi.tiangolo.com/ko/