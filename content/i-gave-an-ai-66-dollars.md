# I gave an AI $66 and had it test 790 trading strategies. None worked.

*Draft for the author to edit. Every number comes from the repo's result files and can be re-derived from it. Built with Claude Code; the AI made real mistakes along the way, listed below.*

I wanted to see what happens if you let an AI agent run a small crypto wallet on its own. I put about $66 on Base (an Ethereum layer 2) and asked it to find a way to grow it, with one rule: **it may never be trusted just because it says so.**

Here is what I learned. The headline: the money lesson is boring, the engineering lesson is not.

## Version 1 looked great and was fake

The first bot ran every 30 minutes, "audited itself" every cycle, and produced a dashboard full of green checks. Then I looked closer:

* Its auditor had passed **2,646 of 2,646** checks. It never disagreed once, because its checks were written so they could not fail.
* "Discovery" was six hardcoded items, re-scored 392 times.
* Its dashboard balance was stale and wrong.
* One transaction paid **8 gwei when the network was charging 0.005**, 1,600 times the going rate, to move about a dollar. That single mistake cost $3.73 and wiped out everything the bot had earned.

Nothing was hacked. The bot simply had no way to be wrong in a way it could notice.

## The rebuild: make the system able to catch itself

Version 2 is called [honest-ledger](https://github.com/arbreton/honest-ledger). The ideas are simple:

1. **The chain is the source of truth.** A hash-chained ledger rebuilds the wallet's full history from raw blockchain data and compares itself to the chain, to the wei, every 15 minutes. If they disagree, everything stops.
2. **The AI can research but cannot sign.** Every transaction is simulated on a copy of mainnet first, must pass a rule gate (gas caps, allowed contracts, exact approvals, payback test), and is signed by a separate process that re-checks its own limits.
3. **An independent auditor** with its own code and its own connection to the chain can halt the system but can never approve anything.
4. **Attack drills.** Eighteen adversarial scenarios, including v1's own 8-gwei transaction, run against the real gate every day. If any one gets through, the system halts.

The point is not that the rules are clever. It is that they live outside the model.

## The experiment: 790 strategies, zero survivors

I then built a research lab to answer the question honestly: *is there any formula that beats just holding ETH?*

It tested **790 strategies**: moving averages, RSI, Bollinger bands, MACD, momentum, Fibonacci retracements, weekly trends, session and weekday effects, leverage up to 5×, and **144 machine-learning models** (logistic regression, gradient boosting, random forests) trained with strict walk-forward rules. Costs, perpetual-futures funding and liquidation were all modelled.

To avoid fooling myself I used three separate time windows (2023-24 to pick, 2025 to confirm, 2026 locked away), and a *deflated Sharpe ratio* that charges you for how many strategies you tried, plus a bootstrap "reality check".

The result:

* **Zero strategies passed.** The reality-check p-value was **1.00**, meaning the best result could easily be luck.
* Only **3%** of strategies beat buy-and-hold in the 2023-24 bull market, **43%** in 2025, and **50%** in 2026. The later "wins" were mostly strategies that happened to be out of a falling market (ETH: ×2.78, then ×0.88, then ×0.72).
* **Machine learning added nothing.** The best model's rank correlation with the next return was **+0.033** and the average was **+0.008**. Accuracy was 50-53% against a 51% coin-flip baseline.
* **Leverage kills.** 71 of the 300 leveraged configurations were liquidated in the backtest; a 2×-5× long of ETH would not have survived 2022.

## The patterns people swear by

I tested these directly, with correction for the number of things tested:

* **"It always sells when Asia opens."** ETH is down on **49%** of days in that window (p = 0.28), and the sign flips between years.
* **"It always jumps on the weekly."** **48%** of 255 weeks were up. Last week predicts this week only weakly (rank correlation +0.10, not significant). Monday predicts nothing.
* **Hour of day and weekday:** none survives multiple-test correction.
* **Fibonacci retracements:** no better than chance, and they lost money in 2025.
* **"ETH still has 8× left":** that needs $17,020, which is **3.5× the old all-time high** ($4,832). The last cycle's high only matched the one before it, so cycle multiples have been shrinking.

One idea did look good: a "cycle runner" that goes full size when ETH is far below its high and keeps a small runner otherwise. It beat buy-and-hold in all three windows. But I designed it after looking at two cycles, so the deflated Sharpe was **0.01**: the data cannot tell it apart from luck. It is now in a forward test, which is the only fair way to judge it.

## Mistakes the AI made, and how they were caught

Honest reporting means including these:

1. It reported a "$2.98 gas cost" for a deposit by trusting v1's logs. Rebuilding the history from the chain showed the real cost was about **$0.05**; the log had counted a token swap as gas.
2. It computed a vault's yield as 0.5% because it assumed 43,200 blocks a day. Base now produces **5 blocks a second**, so the real yield was **5-6%**.
3. It recalled a swap-router address from memory that belonged to the wrong pool factory. Checking the contract on-chain caught it before any money moved.

Each was found by the same habit: *check against the chain, not against the story.*

## What happens next

Fifteen strategies are now paper-trading live, and I pre-registered the pass/fail rules before they produced a single result. With 30 days of data, only an extraordinary strategy could be told apart from luck, so day 30 is a sanity check, and nothing goes near real money before 180 days.

The honest summary: **a small account cannot out-trade the market with these tools, and a system that admits this is worth more than a bot that claims otherwise.** The reusable part is the plumbing, books that reconcile to the chain, a signer that cannot be talked into things, and a lab that tells you when you are fooling yourself.

*Not financial advice. This is an experiment with a tiny amount of money. Code, tests and every figure above: github.com/arbreton/honest-ledger.*
