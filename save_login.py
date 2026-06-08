from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    context = browser.new_context()
    
    page = context.new_page()
    
    page.goto("https://x.com/home")
    
    input("ログイン完了後 Enter を押す")
    
    context.storage_state(path="storage_state.json")
    
    print("保存完了")
    
    browser.close()
