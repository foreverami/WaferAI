from pathlib import Path
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
import io, json, sqlite3, uuid, hashlib
import numpy as np
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from waferai.inference import CLASSES, load_model, predict, preprocess

ROOT = Path(__file__).resolve().parent.parent

def create_app(db_path=None, checkpoint=None):
    db_path = Path(db_path or ROOT/'data/waferai.sqlite3')
    checkpoint = Path(checkpoint or ROOT/'models/best_coatnet_model_optimized.pth')
    lock = Lock()
    @contextmanager
    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    @asynccontextmanager
    async def lifespan(app):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, created TEXT, filename TEXT, map TEXT, result TEXT, model_version TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, record_id TEXT, created TEXT, label TEXT, note TEXT)')
        app.state.model, app.state.metadata = load_model(checkpoint)
        app.state.version = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        yield
    app = FastAPI(title='WaferAI', lifespan=lifespan)
    @app.get('/')
    def home(): return FileResponse(ROOT/'waferai/static/index.html')
    @app.get('/api/status')
    def status():
        return {'model_ready':True,'metadata':app.state.metadata,'model_version':app.state.version,'classes':CLASSES}
    @app.get('/api/records')
    def records():
        with connect() as c:
            rows=c.execute('SELECT id,created,filename,result,model_version FROM records ORDER BY created DESC LIMIT 200').fetchall()
            output=[]
            for row in rows:
                item=dict(row);item['result']=json.loads(item['result'])
                item['review']=dict(r) if (r:=c.execute('SELECT * FROM reviews WHERE record_id=? ORDER BY id DESC LIMIT 1',(item['id'],)).fetchone()) else None
                output.append(item)
            return output
    @app.get('/api/records/{record_id}')
    def detail(record_id: str):
        with connect() as c:
            row=c.execute('SELECT * FROM records WHERE id=?',(record_id,)).fetchone()
            if not row: raise HTTPException(404,'기록이 없습니다')
            item=dict(row)
            for k in ['map','result']:item[k]=json.loads(item[k])
            item['reviews']=[dict(r) for r in c.execute('SELECT * FROM reviews WHERE record_id=? ORDER BY id DESC',(record_id,))]
            return item
    @app.post('/api/predict')
    def inference(file: UploadFile):
        raw=file.file.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: raise HTTPException(413,'파일은 2MB 이하여야 합니다')
        suffix=Path(file.filename or '').suffix.lower()
        try:
            if suffix=='.npy': wm=np.load(io.BytesIO(raw),allow_pickle=False)
            elif suffix=='.csv': wm=np.loadtxt(io.BytesIO(raw),delimiter=',',ndmin=2)
            elif suffix=='.json': wm=np.asarray(json.loads(raw))
            else: raise ValueError('NPY, CSV, JSON 형식만 지원합니다')
            if wm.ndim!=2 or max(wm.shape,default=0)>512: raise ValueError('맵은 최대 512×512의 2차원 배열이어야 합니다')
            preprocess(wm)
        except Exception as e: raise HTTPException(422,f'입력 오류: {e}') from e
        with lock: result=predict(app.state.model,wm)
        record_id=str(uuid.uuid4())
        with connect() as c:
            c.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(record_id,datetime.now(timezone.utc).isoformat(),file.filename,json.dumps(wm.astype(int).tolist()),json.dumps(result),app.state.version))
        return detail(record_id)
    class Review(BaseModel):
        label: Literal['Center','Donut','Edge-Loc','Edge-Ring','Loc','Near-full','Random','Scratch','none']
        note: str = Field(default='',max_length=2000)
    @app.post('/api/records/{record_id}/review')
    def review(record_id: str, body: Review):
        with connect() as c:
            if not c.execute('SELECT id FROM records WHERE id=?',(record_id,)).fetchone():raise HTTPException(404,'기록이 없습니다')
            c.execute('INSERT INTO reviews(record_id,created,label,note) VALUES(?,?,?,?)',(record_id,datetime.now(timezone.utc).isoformat(),body.label,body.note))
        return detail(record_id)
    return app

app=create_app()
