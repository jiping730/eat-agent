import time
from functools import wraps

def performance_stats(func):
    """性能统计装饰器：打印函数执行时间"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"[性能] {func.__name__} 耗时: {end - start:.4f}秒")
        return result
    return wrapper
