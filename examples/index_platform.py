from pydantic import BaseModel

from rh_cognitv_lite.execution_platform import (
    ExecutionPlatform
)
from rh_cognitv_lite.execution_platform.errors import TransientError
from rh_cognitv_lite.execution_platform.event_bus import EventBus
from rh_cognitv_lite.execution_platform.execution import Execution
from rh_cognitv_lite.execution_platform.models import RetryConfig

event_bus = EventBus()
event_bus.subscribe(lambda e: print(f"====> Event: {e}"))
platform = ExecutionPlatform(
    event_bus=event_bus,
)

async def basic_execution():
    
    def handler(value: str):
        print("Hello, Cognitiv!")
        return {"greeting": f"Hello, {value}!"} if value else {"greeting": "Hello, World!"}
        
    await platform(
        Execution(
            name="Nome execução",
            kind="TIPO_EVENTO",
            description='Essa é uma descrição teste',
            input_data={'value': 23},
            handler=handler
        )
    )

async def sequence_execution():
    
    def handler_ok(value: str):
        print("Hello, Cognitiv!")
        return {"greeting": f"Hello, {value}!"} if value else {"greeting": "Hello, World!"}
    def handler_fail(value: str):
        raise TransientError(message='Ops erro teste')
    exec_ok = Execution(
            name="Execuçao Sucesso",
            kind="TIPO_EVENTO",
            description='Essa é uma descrição teste',
            input_data={'value': 23},
            handler=handler_ok
        )
    exec_fail = Execution(
            name="Execução Falha",
            kind="TIPO_EVENTO",
            description='Essa é uma descrição teste',
            input_data={'value': 23},
            handler=handler_fail
        )
    async with platform.sequence(group_name='grupo teste', retry_config=RetryConfig(max_attempts = 3)) as seq:
        seq.add(exec_ok)
        seq.add(exec_fail)
        print('Result', await seq.run())
        

async def parallel_execution():
    
    def handler(value: str):
        print("Hello, Cognitiv!")
        return {"greeting": f"Hello, {value}!"} if value else {"greeting": "Hello, World!"}
    exec = Execution(
            name="Nome execução",
            kind="TIPO_EVENTO",
            description='Essa é uma descrição teste',
            input_data={'value': 23},
            handler=handler
        )
    async with platform.parallel(group_name='grupo teste', retry_config=RetryConfig(max_attempts = 3)) as par:
        par.add(exec)
        par.add(exec)
        print('Result', await par.run())

async def main():
    #await basic_execution()
    #await sequence_execution()
    await parallel_execution()
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())