import asyncio


def before_all(context):
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)


def after_all(context):
    context.loop.close()
