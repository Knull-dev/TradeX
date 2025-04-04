import os
import os
from dotenv import load_dotenv

load_dotenv()
import discord
from discord.ext import commands, tasks
import asyncio
import json
import random
import datetime
import aiohttp
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('stock_bot')

# Constants
DEFAULT_STARTING_BALANCE = 10000.0
STOCKS_DATA_FILE = 'stocks_data.json'
USERS_DATA_FILE = 'users_data.json'
PRICE_UPDATE_INTERVAL = 60  # seconds
ALPHA_VANTAGE_API_KEY = 'YOUR_ALPHA_VANTAGE_API_KEY'  # Replace with your actual API key
DEFAULT_STOCK_SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'JPM', 'V', 'WMT']

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='$', intents=intents)

# Data storage
users_data = {}
stocks_data = {}

# Helper functions for data management
def load_data():
    global users_data, stocks_data
    
    # Load users data
    try:
        if os.path.exists(USERS_DATA_FILE):
            with open(USERS_DATA_FILE, 'r') as f:
                users_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading users data: {e}")
        users_data = {}
    
    # Load stocks data
    try:
        if os.path.exists(STOCKS_DATA_FILE):
            with open(STOCKS_DATA_FILE, 'r') as f:
                stocks_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading stocks data: {e}")
        stocks_data = {}
        
def save_data():
    # Save users data
    with open(USERS_DATA_FILE, 'w') as f:
        json.dump(users_data, f, indent=4)
    
    # Save stocks data
    with open(STOCKS_DATA_FILE, 'w') as f:
        json.dump(stocks_data, f, indent=4)

async def fetch_stock_price(symbol: str) -> Optional[float]:
    """Fetch real stock price from Alpha Vantage API"""
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check if we got valid data
                    if "Global Quote" in data and "05. price" in data["Global Quote"]:
                        price = float(data["Global Quote"]["05. price"])
                        logger.info(f"Successfully fetched price for {symbol}: ${price}")
                        return price
                    else:
                        # Check if we hit API limit
                        if "Note" in data:
                            logger.warning(f"Alpha Vantage API limit reached: {data['Note']}")
                        else:
                            logger.warning(f"No price data for {symbol} in response: {data}")
                        return None
                else:
                    logger.error(f"API request failed with status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching stock price for {symbol}: {e}")
        return None

# For testing/development when you don't want to use Alpha Vantage or hit API limits
def generate_mock_price(symbol: str) -> float:
    """Generate a mock price for testing purposes"""
    base_price = hash(symbol) % 1000  # deterministic base price
    if symbol not in stocks_data:
        stocks_data[symbol] = {"current_price": base_price}
        return base_price
    
    # Fluctuate price by small percentage
    current_price = stocks_data[symbol]["current_price"]
    change_percent = (random.random() - 0.5) * 0.05  # -2.5% to +2.5%
    new_price = current_price * (1 + change_percent)
    return round(new_price, 2)

async def fetch_stock_info(symbol: str) -> dict:
    """Fetch stock information from Alpha Vantage"""
    try:
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check if we got valid data
                    if "Symbol" in data:
                        return data
                    else:
                        logger.warning(f"No company overview data for {symbol}")
                        return {}
                else:
                    logger.error(f"API request failed with status {response.status}")
                    return {}
    except Exception as e:
        logger.error(f"Error fetching stock info for {symbol}: {e}")
        return {}

# Task to update stock prices
@tasks.loop(seconds=PRICE_UPDATE_INTERVAL)
async def update_stock_prices():
    """Update prices for all tracked stocks"""
    if not stocks_data:
        return
    
    for symbol in list(stocks_data.keys()):
        try:
            # Use Alpha Vantage API with rate limiting
            # Alpha Vantage free tier allows 5 API calls per minute
            price = await fetch_stock_price(symbol)
            
            # Fall back to mock data if Alpha Vantage fails or limits reached
            if price is None:
                price = generate_mock_price(symbol)
                logger.info(f"Using mock price for {symbol}: ${price}")
            else:
                logger.info(f"Got real price for {symbol}: ${price}")
            
            # Record price history (keeping last 24 hours of data)
            timestamp = datetime.datetime.now().isoformat()
            if "history" not in stocks_data[symbol]:
                stocks_data[symbol]["history"] = []
            
            stocks_data[symbol]["history"].append({"time": timestamp, "price": price})
            # Keep only last 24 data points (e.g., last 24 hours if hourly updates)
            if len(stocks_data[symbol]["history"]) > 24:
                stocks_data[symbol]["history"] = stocks_data[symbol]["history"][-24:]
            
            # Update current price
            old_price = stocks_data[symbol].get("current_price", price)
            stocks_data[symbol]["current_price"] = price
            stocks_data[symbol]["percent_change"] = ((price - old_price) / old_price) * 100 if old_price > 0 else 0
            
            # Add a delay to avoid hitting API rate limits
            await asyncio.sleep(13)  # Sleep for 13 seconds to stay under 5 requests per minute
        except Exception as e:
            logger.error(f"Error updating price for {symbol}: {e}")
    
    save_data()

# Bot Events
@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    load_data()
    
    # Add default stocks if they don't exist
    for symbol in DEFAULT_STOCK_SYMBOLS:
        if symbol not in stocks_data:
            try:
                # Use mock price initially, real prices will be updated by the update_stock_prices task
                price = generate_mock_price(symbol)
                
                stocks_data[symbol] = {
                    "current_price": price,
                    "history": [{"time": datetime.datetime.now().isoformat(), "price": price}],
                    "percent_change": 0.0
                }
                logger.info(f"Added default stock {symbol} at initial price ${price}")
            except Exception as e:
                logger.error(f"Failed to add default stock {symbol}: {e}")
    
    if DEFAULT_STOCK_SYMBOLS:
        save_data()
        
    update_stock_prices.start()

# Commands
@bot.command(name='register', help='Register to play the stock market game')
async def register(ctx):
    user_id = str(ctx.author.id)
    
    if user_id in users_data:
        await ctx.send(f"You're already registered, {ctx.author.name}!")
        return
    
    users_data[user_id] = {
        "balance": DEFAULT_STARTING_BALANCE,
        "portfolio": {},
        "transactions": []
    }
    
    save_data()
    await ctx.send(f"Welcome to the Stock Market Game, {ctx.author.name}! You've been given ${DEFAULT_STARTING_BALANCE:,.2f} to start.")

@bot.command(name='balance', help='Check your current balance')
async def balance(ctx):
    user_id = str(ctx.author.id)
    
    if user_id not in users_data:
        await ctx.send(f"You're not registered yet! Use `$register` to start playing.")
        return
    
    balance = users_data[user_id]["balance"]
    
    # Calculate portfolio value
    portfolio_value = 0
    for symbol, shares in users_data[user_id]["portfolio"].items():
        if symbol in stocks_data and "current_price" in stocks_data[symbol]:
            portfolio_value += stocks_data[symbol]["current_price"] * shares
    
    total_value = balance + portfolio_value
    
    embed = discord.Embed(title=f"{ctx.author.name}'s Financial Status", color=0x00ff00)
    embed.add_field(name="Cash Balance", value=f"${balance:,.2f}", inline=False)
    embed.add_field(name="Portfolio Value", value=f"${portfolio_value:,.2f}", inline=False)
    embed.add_field(name="Total Net Worth", value=f"${total_value:,.2f}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='add_stock', help='Add a stock to the market (Admin only)')
@commands.has_permissions(administrator=True)
async def add_stock(ctx, symbol: str, price: float = None):
    symbol = symbol.upper()
    
    if price is None:
        try:
            # Use Alpha Vantage API
            price = await fetch_stock_price(symbol)
            
            # Fall back to mock data if Alpha Vantage fails
            if price is None:
                price = generate_mock_price(symbol)
                await ctx.send(f"Could not fetch real price for {symbol}. Using mock price: ${price:,.2f}")
            else:
                await ctx.send(f"Successfully fetched real price for {symbol}: ${price:,.2f}")
        except Exception as e:
            price = generate_mock_price(symbol)
            await ctx.send(f"Error fetching price for {symbol}: {e}. Using mock price: ${price:,.2f}")
    
    stocks_data[symbol] = {
        "current_price": price,
        "history": [{"time": datetime.datetime.now().isoformat(), "price": price}],
        "percent_change": 0.0
    }
    
    save_data()
    await ctx.send(f"Added {symbol} to the market at ${price:,.2f}")

@bot.command(name='price', help='Check the current price of a stock')
async def price(ctx, symbol: str):
    symbol = symbol.upper()
    
    if symbol not in stocks_data:
        # Try to get price from Alpha Vantage directly, even if not tracked
        try:
            price = await fetch_stock_price(symbol)
            if price:
                await ctx.send(f"{symbol} is currently priced at ${price:,.2f} (not tracked in game)")
                await ctx.send(f"Ask an admin to add it with `$add_stock {symbol}`")
                return
        except:
            pass
        
        await ctx.send(f"Stock {symbol} is not tracked. Ask an admin to add it with `$add_stock {symbol}`")
        return
    
    current_price = stocks_data[symbol].get("current_price", 0)
    percent_change = stocks_data[symbol].get("percent_change", 0)
    
    # Determine color based on percent change
    if percent_change > 0:
        color = 0x00ff00  # Green
    elif percent_change < 0:
        color = 0xff0000  # Red
    else:
        color = 0x808080  # Gray
    
    embed = discord.Embed(title=f"{symbol} Stock Info", color=color)
    embed.add_field(name="Current Price", value=f"${current_price:,.2f}", inline=True)
    embed.add_field(name="Change", value=f"{percent_change:+.2f}%", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='buy', help='Buy shares of a stock')
async def buy(ctx, symbol: str, shares: int):
    user_id = str(ctx.author.id)
    symbol = symbol.upper()
    
    # Validations
    if user_id not in users_data:
        await ctx.send(f"You're not registered yet! Use `$register` to start playing.")
        return
    
    if symbol not in stocks_data:
        await ctx.send(f"Stock {symbol} is not tracked. Ask an admin to add it.")
        return
    
    if shares <= 0:
        await ctx.send("You must buy at least 1 share.")
        return
    
    price = stocks_data[symbol].get("current_price", 0)
    total_cost = price * shares
    
    if users_data[user_id]["balance"] < total_cost:
        await ctx.send(f"You don't have enough money! Cost: ${total_cost:,.2f}, Your balance: ${users_data[user_id]['balance']:,.2f}")
        return
    
    # Process purchase
    users_data[user_id]["balance"] -= total_cost
    
    if symbol not in users_data[user_id]["portfolio"]:
        users_data[user_id]["portfolio"][symbol] = 0
    
    users_data[user_id]["portfolio"][symbol] += shares
    
    # Record transaction
    transaction = {
        "type": "buy",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "total": total_cost,
        "timestamp": datetime.datetime.now().isoformat()
    }
    users_data[user_id]["transactions"].append(transaction)
    
    save_data()
    
    embed = discord.Embed(title="Purchase Successful", color=0x00ff00)
    embed.add_field(name="Stock", value=symbol, inline=True)
    embed.add_field(name="Shares", value=str(shares), inline=True)
    embed.add_field(name="Price per Share", value=f"${price:,.2f}", inline=True)
    embed.add_field(name="Total Cost", value=f"${total_cost:,.2f}", inline=True)
    embed.add_field(name="New Balance", value=f"${users_data[user_id]['balance']:,.2f}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='sell', help='Sell shares of a stock')
async def sell(ctx, symbol: str, shares: int):
    user_id = str(ctx.author.id)
    symbol = symbol.upper()
    
    # Validations
    if user_id not in users_data:
        await ctx.send(f"You're not registered yet! Use `$register` to start playing.")
        return
    
    if symbol not in stocks_data:
        await ctx.send(f"Stock {symbol} is not tracked.")
        return
    
    if shares <= 0:
        await ctx.send("You must sell at least 1 share.")
        return
    
    if symbol not in users_data[user_id]["portfolio"] or users_data[user_id]["portfolio"][symbol] < shares:
        owned = users_data[user_id]["portfolio"].get(symbol, 0)
        await ctx.send(f"You don't have enough shares! You own {owned} shares of {symbol}.")
        return
    
    # Process sale
    price = stocks_data[symbol].get("current_price", 0)
    total_value = price * shares
    
    users_data[user_id]["balance"] += total_value
    users_data[user_id]["portfolio"][symbol] -= shares
    
    # Remove stock from portfolio if no shares left
    if users_data[user_id]["portfolio"][symbol] == 0:
        del users_data[user_id]["portfolio"][symbol]
    
    # Record transaction
    transaction = {
        "type": "sell",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "total": total_value,
        "timestamp": datetime.datetime.now().isoformat()
    }
    users_data[user_id]["transactions"].append(transaction)
    
    save_data()
    
    embed = discord.Embed(title="Sale Successful", color=0x0000ff)
    embed.add_field(name="Stock", value=symbol, inline=True)
    embed.add_field(name="Shares", value=str(shares), inline=True)
    embed.add_field(name="Price per Share", value=f"${price:,.2f}", inline=True)
    embed.add_field(name="Total Value", value=f"${total_value:,.2f}", inline=True)
    embed.add_field(name="New Balance", value=f"${users_data[user_id]['balance']:,.2f}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='portfolio', help='View your stock portfolio')
async def portfolio(ctx):
    user_id = str(ctx.author.id)
    
    if user_id not in users_data:
        await ctx.send(f"You're not registered yet! Use `$register` to start playing.")
        return
    
    portfolio = users_data[user_id]["portfolio"]
    
    if not portfolio:
        await ctx.send(f"You don't own any stocks yet. Use `$buy` to purchase some!")
        return
    
    embed = discord.Embed(title=f"{ctx.author.name}'s Portfolio", color=0x00ffff)
    
    total_value = 0
    for symbol, shares in portfolio.items():
        if symbol in stocks_data and "current_price" in stocks_data[symbol]:
            price = stocks_data[symbol]["current_price"]
            value = price * shares
            total_value += value
            
            # Calculate profit/loss if we have transaction history
            cost_basis = 0
            for transaction in users_data[user_id]["transactions"]:
                if transaction["symbol"] == symbol and transaction["type"] == "buy":
                    cost_basis += transaction["total"]
                elif transaction["symbol"] == symbol and transaction["type"] == "sell":
                    cost_basis -= transaction["total"]
            
            profit_loss = value - cost_basis
            pl_percent = (profit_loss / cost_basis) * 100 if cost_basis > 0 else 0
            
            embed.add_field(
                name=f"{symbol} ({shares} shares)",
                value=f"Price: ${price:,.2f}\nValue: ${value:,.2f}\nP/L: ${profit_loss:,.2f} ({pl_percent:+.2f}%)",
                inline=True
            )
    
    embed.add_field(name="Total Portfolio Value", value=f"${total_value:,.2f}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='market', help='See all available stocks')
async def market(ctx):
    if not stocks_data:
        await ctx.send("No stocks are currently tracked in the market.")
        return
    
    embed = discord.Embed(title="Stock Market", color=0xffff00)
    
    for symbol, data in stocks_data.items():
        price = data.get("current_price", 0)
        change = data.get("percent_change", 0)
        
        # Add emoji based on performance
        if change > 2:
            emoji = "🚀"  # Rocket for big gains
        elif change > 0:
            emoji = "📈"  # Chart up
        elif change < -2:
            emoji = "💥"  # Crash
        elif change < 0:
            emoji = "📉"  # Chart down
        else:
            emoji = "➡️"  # Sideways
        
        embed.add_field(
            name=f"{symbol} {emoji}",
            value=f"${price:,.2f} ({change:+.2f}%)",
            inline=True
        )
    
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Show the richest players')
async def leaderboard(ctx):
    if not users_data:
        await ctx.send("No players have registered yet!")
        return
    
    # Calculate net worth for each user
    net_worths = []
    for user_id, data in users_data.items():
        balance = data["balance"]
        portfolio_value = 0
        
        for symbol, shares in data["portfolio"].items():
            if symbol in stocks_data and "current_price" in stocks_data[symbol]:
                portfolio_value += stocks_data[symbol]["current_price"] * shares
        
        net_worth = balance + portfolio_value
        
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"User {user_id}"
        
        net_worths.append({
            "username": username,
            "net_worth": net_worth
        })
    
    # Sort by net worth (descending)
    net_worths.sort(key=lambda x: x["net_worth"], reverse=True)
    
    embed = discord.Embed(title="Stock Market Game Leaderboard", color=0xffd700)
    
    # Display top 10
    for i, entry in enumerate(net_worths[:10], 1):
        embed.add_field(
            name=f"{i}. {entry['username']}",
            value=f"${entry['net_worth']:,.2f}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='help_stocks', help='Display help for stock market commands')
async def help_stocks(ctx):
    embed = discord.Embed(title="Stock Market Game - Help", color=0x1e90ff)
    
    commands = [
        {"name": "$register", "desc": "Create an account with $10,000 starting cash"},
        {"name": "$balance", "desc": "Check your current cash balance and portfolio value"},
        {"name": "$market", "desc": "See all available stocks and their prices"},
        {"name": "$price SYMBOL", "desc": "Check the current price of a specific stock"},
        {"name": "$buy SYMBOL SHARES", "desc": "Buy shares of a stock"},
        {"name": "$sell SYMBOL SHARES", "desc": "Sell shares of a stock"},
        {"name": "$portfolio", "desc": "View your current stock holdings"},
        {"name": "$leaderboard", "desc": "See who has the highest net worth"},
        {"name": "$info SYMBOL", "desc": "Get detailed information about a stock"},
        {"name": "$add_stock SYMBOL [PRICE]", "desc": "Add a new stock (admin only)"}
    ]
    
    for cmd in commands:
        embed.add_field(name=cmd["name"], value=cmd["desc"], inline=False)
    
    await ctx.send(embed=embed)

# Command to look up stock information
@bot.command(name='info', help='Get information about a stock')
async def stock_info(ctx, symbol: str):
    symbol = symbol.upper()
    
    try:
        stock_data = await fetch_stock_info(symbol)
        
        if not stock_data:
            await ctx.send(f"Could not find information for {symbol}")
            return
        
        embed = discord.Embed(title=f"{stock_data.get('Name', symbol)} ({symbol})", color=0x1e90ff)
        
        # Basic info
        if "Sector" in stock_data:
            embed.add_field(name="Sector", value=stock_data["Sector"], inline=True)
        if "Industry" in stock_data:
            embed.add_field(name="Industry", value=stock_data["Industry"], inline=True)
        if "Country" in stock_data:
            embed.add_field(name="Country", value=stock_data["Country"], inline=True)
        
        # Price info
        if symbol in stocks_data and "current_price" in stocks_data[symbol]:
            current_price = stocks_data[symbol]["current_price"]
            embed.add_field(name="Current Price", value=f"${current_price:,.2f}", inline=True)
        
        # Financial metrics
        metrics = []
        if "MarketCapitalization" in stock_data and stock_data["MarketCapitalization"]:
            market_cap = float(stock_data["MarketCapitalization"]) / 1000000000
            metrics.append(f"Market Cap: ${market_cap:,.2f}B")
        if "PERatio" in stock_data and stock_data["PERatio"] and stock_data["PERatio"] != "None":
            metrics.append(f"P/E: {float(stock_data['PERatio']):.2f}")
        if "DividendYield" in stock_data and stock_data["DividendYield"] and stock_data["DividendYield"] != "None":
            div_yield = float(stock_data["DividendYield"]) * 100
            metrics.append(f"Dividend Yield: {div_yield:.2f}%")
        if "EPS" in stock_data and stock_data["EPS"] and stock_data["EPS"] != "None":
            metrics.append(f"EPS: ${float(stock_data['EPS']):.2f}")
        
        if metrics:
            embed.add_field(name="Key Metrics", value="\n".join(metrics), inline=False)
        
        # Business description
        if "Description" in stock_data and stock_data["Description"]:
            description = stock_data["Description"]
            if len(description) > 1024:
                description = description[:1021] + "..."
            embed.add_field(name="Business Description", value=description, inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error fetching information for {symbol}: {str(e)}")

def main():
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_TOKEN is not set in environment variables.")
        return
    bot.run(TOKEN)

if __name__ == "__main__":
    main()