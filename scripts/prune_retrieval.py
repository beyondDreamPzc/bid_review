"""Dry-run by default. Remove only old non-current, inactive Milvus projections; retain MySQL facts."""
import argparse
from datetime import timedelta
import json
from sqlalchemy import select
from app import models as m
from app.config import get_settings
from app.database import SessionLocal
from app.retrieval import projection


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--project-id",required=True);parser.add_argument("--older-than-days",type=int,default=30)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if args.older_than_days<1:parser.error("Retention must be at least one day")
    selected=[]
    with SessionLocal() as db:
        project=db.get(m.Project,args.project_id)
        if not project:raise RuntimeError("Project not found")
        for index,job in db.execute(select(m.RetrievalIndex,m.Job).join(m.Job)
                .where(m.RetrievalIndex.project_id==project.id,m.RetrievalIndex.created_at<m.utcnow()-timedelta(days=args.older_than_days))):
            if index.material_set_id==project.current_material_set_id or job.status in {"QUEUED","RUNNING","RETRY_WAIT"}:continue
            selected.append((index.id,index.profile))
    for index_id,profile in selected:
        if args.apply:
            client=projection(get_settings(),profile)
            if client.call("collections/has")["has"]:
                client.call("entities/delete",filter=f"project == {json.dumps(args.project_id)} and generation like {json.dumps(index_id+':%')}")
    print(json.dumps({"dry_run":not args.apply,"old_inactive_indexes":len(selected),"mysql_history_retained":True}))


if __name__=="__main__":main()
