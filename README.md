#backtest.ai

## Inspiration
Everyone loves money, and many seek to grow their wealth through capital markets, whether for short or long durations. However, identifying the right stock for short-term or long-term gains can be risky and cumbersome. In Peter Lynch's *One Up on Wall Street*, he emphasizes the importance of investing in companies that consistently buy back their shares. Inspired by this, I envisioned a tool that calculates the returns from buybacks, bonuses, and stock splits, providing long-term and short-term insights along with LLM-based reasoning for trade and investment ideas.

Currently, this tool covers only the listed companies in India, but I have plans to expand its capabilities to encompass all capital markets in the future.

## What It Does
backtest.ai provides insights into stock performance based on corporate actions such as buybacks, bonuses, and splits. It calculates returns over short and long-term periods and offers reasoning for investment decisions through natural language processing.

## How We Built It
India's stock market corporate actions data is not readily available, so I developed a script that extracts corporate actions for a given company. This data is streamed to a Redpanda connector, producing messages that are written to a Supabase-hosted PostgreSQL database on the consumer side.

The Python application utilizes LLMs to identify stock tickers and corporate actions with appropriate handling. Once identified, it generates return data for both short and long-term time frames. This return data is then analyzed by the LLM to provide reasoning regarding the viability of specific trades based on corporate actions.

## Challenges We Ran Into
- Lack of readily available corporate actions data for Indian stocks.
- Implementing a robust data streaming solution with Redpanda.
- Ensuring accurate identification and handling of stock tickers and corporate actions.

## Accomplishments That We're Proud Of
- Successfully integrated Redpanda for real-time data streaming.
- Developed a functional tool that analyzes corporate actions and provides actionable insights.
- Created a natural language backtesting platform that facilitates hypothesis testing for investment strategies.

## What We Learned
I gained valuable experience in data streaming with Redpanda, which is crucial for managing stock market data. Additionally, I learned about building a natural language backtesting platform capable of testing corporate actions on specific companies.

## What's Next for backtest.ai
Future plans include expanding backtesting features across various areas of the capital markets, enhancing the tool's capabilities, and broadening its reach to more companies and markets globally.


## Demo Screenshots

<img width="1359" alt="Screenshot 2024-10-28 at 9 40 39 PM" src="https://github.com/user-attachments/assets/799c1e6f-84db-4e62-bdd7-b2a594697bf4">




