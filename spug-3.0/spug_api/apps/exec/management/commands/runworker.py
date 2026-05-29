# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connections
from django_redis import get_redis_connection
from concurrent.futures import ThreadPoolExecutor
from apps.exec.executors import exec_worker_handler
from threading import Thread
import logging
import time
import os

EXEC_WORKER_KEY = settings.EXEC_WORKER_KEY

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')


class Worker:
    def __init__(self):
        self.rds = get_redis_connection()
        self._executor = ThreadPoolExecutor(max_workers=max(100, os.cpu_count() * 50))

    def job_done(self, future):
        connections.close_all()

    def queue_monitor(self):
        counter = 0
        while True:
            time.sleep((counter or 1) ** 3 * 10)
            qsize = self._executor._work_queue.qsize()
            if qsize > 0:
                if counter > 0:
                    connections.close_all()
                    logging.warning(f'!!! 执行队列堆积（{qsize}）')
                counter += 1
            else:
                counter = 0

    def run(self):
        logging.warning('Running worker')
        Thread(target=self.queue_monitor, daemon=True).start()
        self.rds.delete(EXEC_WORKER_KEY)
        while True:
            key, job = self.rds.blpop(EXEC_WORKER_KEY)
            key = key.decode()
            if key == EXEC_WORKER_KEY:
                future = self._executor.submit(exec_worker_handler, job)
            else:
                continue
            future.add_done_callback(self.job_done)


class Command(BaseCommand):
    help = 'Start worker process'

    def handle(self, *args, **options):
        w = Worker()
        w.run()
