import asyncio

async def main():
    print("bot started")

    while True:
        print("running...")
        await asyncio.sleep(60)  # 1分待機して生存

if __name__ == "__main__":
    asyncio.run(main())
