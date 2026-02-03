from redis import Redis
from rq import Queue

from .config import settings

redis_conn = Redis.from_url(settings.redis_url)
build_queue = Queue("builds", connection=redis_conn)
control_queue = Queue("controls", connection=redis_conn)
