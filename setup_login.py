import asyncio
from playwright.async_api import async_playwright


async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=False)

        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://x.com/login")

        input("ログイン完了したらEnter →")

        await context.storage_state(path="state.json")

        await browser.close()

        print("ログイン保存完了")


if __name__ == "__main__":
    asyncio.run(main())