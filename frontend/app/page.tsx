export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24" data-testid="home-page">
      <div className="z-10 max-w-5xl w-full items-center justify-center font-mono text-sm">
        <h1 className="text-4xl font-bold mb-4" data-testid="home-title">AP2 Demo App v2</h1>
        <p className="text-lg text-muted-foreground mb-8" data-testid="home-subtitle">
          Agent Payments Protocol - Microservices Architecture
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-8">
          <a
            href="/chat"
            className="group rounded-lg border border-gray-300 px-5 py-4 transition-colors hover:border-gray-400 hover:bg-gray-100 hover:dark:border-neutral-700 hover:dark:bg-neutral-800/30"
            data-testid="nav-shopping-chat"
          >
            <h2 className="mb-3 text-2xl font-semibold">
              Shopping Chat{" "}
              <span className="inline-block transition-transform group-hover:translate-x-1 motion-reduce:transform-none">
                →
              </span>
            </h2>
            <p className="m-0 max-w-[30ch] text-sm opacity-50">
              AIエージェントとチャットして商品を購入
            </p>
          </a>

          <a
            href="/payment-methods"
            className="group rounded-lg border border-blue-300 px-5 py-4 transition-colors hover:border-blue-400 hover:bg-blue-50 hover:dark:border-blue-700 hover:dark:bg-blue-900/30"
            data-testid="nav-payment-methods"
          >
            <h2 className="mb-3 text-2xl font-semibold">
              支払い方法管理{" "}
              <span className="inline-block transition-transform group-hover:translate-x-1 motion-reduce:transform-none">
                →
              </span>
            </h2>
            <p className="m-0 max-w-[30ch] text-sm opacity-50">
              クレジットカードの登録・削除
            </p>
          </a>

          <a
            href="/merchant"
            className="group rounded-lg border border-gray-300 px-5 py-4 transition-colors hover:border-gray-400 hover:bg-gray-100 hover:dark:border-neutral-700 hover:dark:bg-neutral-800/30"
            data-testid="nav-merchant-dashboard"
          >
            <h2 className="mb-3 text-2xl font-semibold">
              Merchant Dashboard{" "}
              <span className="inline-block transition-transform group-hover:translate-x-1 motion-reduce:transform-none">
                →
              </span>
            </h2>
            <p className="m-0 max-w-[30ch] text-sm opacity-50">
              在庫管理とCartMandate署名
            </p>
          </a>
        </div>

        <div className="mt-12 text-center">
          <p className="text-sm text-muted-foreground">
            Powered by FastAPI + Next.js + Docker Compose
          </p>
        </div>
      </div>
    </main>
  );
}
