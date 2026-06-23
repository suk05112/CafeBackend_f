"""System monitoring endpoints (disk, docker, cleanup)"""
import shutil
import subprocess
import traceback
from fastapi import APIRouter, HTTPException
from core.exceptions import InternalError

router = APIRouter()


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


@router.get("/disk")
def get_disk_usage():
    try:
        usage = shutil.disk_usage("/")
        total_gb = round(usage.total / (1024 ** 3), 2)
        used_gb = round(usage.used / (1024 ** 3), 2)
        free_gb = round(usage.free / (1024 ** 3), 2)
        percent = round(usage.used / usage.total * 100, 1)
        return {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "percent": percent,
        }
    except Exception as e:
        raise InternalError(e, "get_disk_usage")


@router.get("/docker")
def get_docker_usage():
    try:
        output = _run(["docker", "system", "df", "--format", "json"])
        # docker system df --format json outputs one JSON object per line (BuildKit 제외)
        lines = [line for line in output.splitlines() if line.strip().startswith("{")]

        result = {"images": None, "containers": None, "volumes": None, "build_cache": None, "raw": output}

        for line in lines:
            import json
            obj = json.loads(line)
            t = obj.get("Type", "")
            entry = {
                "total": obj.get("TotalCount", obj.get("Total", "")),
                "active": obj.get("Active", ""),
                "size": obj.get("Size", ""),
                "reclaimable": obj.get("Reclaimable", ""),
            }
            if t == "Images":
                result["images"] = entry
            elif t == "Containers":
                result["containers"] = entry
            elif t == "Local Volumes":
                result["volumes"] = entry
            elif t == "Build Cache":
                result["build_cache"] = entry

        # fallback: --format json 미지원 시 텍스트 파싱
        if all(v is None for k, v in result.items() if k != "raw"):
            result["raw"] = _run(["docker", "system", "df"])

        return result
    except Exception as e:
        raise InternalError(e, "get_docker_usage")


@router.post("/cleanup")
def run_cleanup():
    try:
        output = _run(["docker", "system", "prune", "-f"])
        return {"success": True, "output": output}
    except Exception as e:
        raise InternalError(e, "run_cleanup")
