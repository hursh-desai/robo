import smtplib
from email.message import EmailMessage
import os
gmail_user = 'bot.hursh@gmail.com'
gmail_password = os.environ.get('API_PASSPHRASE')
to = 'hurshdesai8@gmail.com'

def send_email(msg, subject):
    msg['Subject'] = subject
    msg['From'] = gmail_user
    msg['To'] = to
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(gmail_user, gmail_password)
    server.send_message(msg)
    server.quit()
    print("Email Sent!")
    
def update(product_id, key, value):
    with open("product_info.json", "r") as f:
        data = json.load(f)

    data[product_id][key] = value

    with open("product_info.json", "w") as f:
        json.dump(data, f)
        
def get(product_id, key):
    with open("product_info.json", "r") as f:
        data = json.load(f)
        return data[product_id][key]

import json
import hmac
import hashlib
import time
import requests
import base64
import urllib
import websocket, json 
from requests.auth import AuthBase
# Create custom authentication for Exchange
class CoinbaseExchangeAuth(AuthBase):
    def __init__(self, api_key, secret_key, passphrase):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def __call__(self, request):
        timestamp = str(time.time())
        message = timestamp + request.method + request.path_url + (request.body or '')
        
        hmac_key = base64.b64decode(self.secret_key)
        
        signature = hmac.new(hmac_key, message.encode('utf-8'), hashlib.sha256)
        
        signature_b64 = base64.b64encode(signature.digest()).rstrip(b'\n')

        request.headers.update({
            'CB-ACCESS-SIGN': signature_b64,
            'CB-ACCESS-TIMESTAMP': timestamp,
            'CB-ACCESS-KEY': self.api_key,
            'CB-ACCESS-PASSPHRASE': self.passphrase,
            "Accept": "application/json",
            'Content-type': 'application/json'
        })
        return request

API_KEY = os.environ.get('API_KEY')
SECRET_KEY = os.environ.get('SECRET_KEY')
API_PASSPHRASE = os.environ.get('API_PASSPHRASE')

# Get accounts
api_url = 'https://api.exchange.coinbase.com' 
auth = CoinbaseExchangeAuth(API_KEY,SECRET_KEY,API_PASSPHRASE)

def place_order(side, product_id, size, price, round_base, round_quote, stop=''):
    order = {}
    order['type'] = 'limit'
    order['product_id'] = product_id
    order['size'] = round(size, round_base)
    order['price'] = round(price, round_quote)
    order['side'] = side
    
    if stop == 'entry':
        order['stop'] = 'entry'
        order['stop_price'] = round(price, round_quote)
        order['side'] = 'buy'
    elif stop == 'loss':
        order['stop'] = 'loss'
        order['stop_price'] = round(price, round_quote)
        order['side'] = 'sell'
        
    r = requests.post(api_url + '/orders', auth=auth, data=json.dumps(order))
    if 'message' in r.json().keys(): 
        print(f'Failed trying to create {stop} limit order {side}ing {order["size"]} of {product_id} at {order["price"]}')
        message = r.json()['message']
        if 'size is too small' in message:
            print('reached money limit')
            msg = EmailMessage()
            msg.set_content(f'Failed trying to create {stop} limit order {side}ing {order["size"]} of {product_id} at {order["price"]}: {message}')
            send_email(msg, 'Subject: Not enough money!')
            return 'nothing'
        elif 'Insufficient funds' in message:
            print(f'Not enough funds to make limit {side}')
            msg = EmailMessage()
            msg.set_content('Not enough {which}'.format(which='USD to buy' if side=='buy' else 'crypto to sell\n'+
            f'Failed trying to create {stop} limit order {side}ing {order["size"]} of {product_id} at {order["price"]}'))
            send_email(msg, f'Subject: Not enough funds to create limit {side}!')
            return 'nothing'
        else:
            print('unkown error')
            print(message)
            msg = EmailMessage()
            msg.set_content(f'Unknown Error: {message}')
            send_email(msg, 'Subject: Unknown Error!')
            return 'nothing'
            
    print('Created {type} {side} order for {} at {} and {} size.'.format(order['product_id'], order['price'], order['size'], type=order['type'] if stop=='' else 'stop ' + order['stop'], side=order['side'] if stop=='' else ''))
    order_id = r.json()['id']
    return order_id

def place_orders(product_id, new_basis, balance, money_limit, round_base, round_quote):
    sell_size = balance * .34
    sell_price = new_basis * 1.06
    
    stop_loss_size = balance *.64
    stop_loss_price = new_basis * .76
    
    first_buy_price = new_basis * .94
    second_buy_price = new_basis * .88
    third_buy_price = new_basis * .82
    
    first_buy_size = (money_limit * .19) / first_buy_price
    second_buy_size = (money_limit * .3) / second_buy_price
    third_buy_size = (money_limit * .49) / third_buy_price
    
    order_id_1 = place_order('sell', product_id, sell_size, sell_price, round_base, round_quote)
    
    order_id_2 = place_order('buy', product_id, first_buy_size, first_buy_price, round_base, round_quote)
    order_id_3 = place_order('buy', product_id, second_buy_size, second_buy_price, round_base, round_quote)
    order_id_4 = place_order('buy', product_id, third_buy_size, third_buy_price, round_base, round_quote)
    order_id_5 = place_order('sell', product_id, stop_loss_size, stop_loss_price, round_base, round_quote, 'loss')
    return order_id_1, order_id_5

import asyncio
from copra.websocket import Channel, Client
with open("money_limits.json", "r") as f:
    tracking = list(json.load(f).keys())

class Ticker(Client):
    def change_sell_order(self, product_id, round_base, round_quote):
        old_bal = get(product_id, 'balance')
        
        accounts = requests.get(api_url + '/accounts', auth=auth)
        currency_pair = product_id.partition('-')
        balance_as_list = [x['balance'] for x in accounts.json() if x['currency'] == currency_pair[0]]
        update(product_id, 'balance', float(balance_as_list[0]))
        
        update(product_id, 'running_avg', (get(product_id, 'balance') - old_bal) * get(product_id, 'price'))

        new_sell_price = (get(product_id, 'running_avg') * 1.06)/get(product_id, 'balance')
    # cancel and place sell order
        if get(product_id, 'sell_id') != '' or get(product_id, 'sell_id') != 'nothing':
            r = requests.delete(api_url + '/orders/' + get(product_id, 'sell_id'), auth=auth)
            new_sell_id = place_order('sell', product_id, get(product_id, 'balance') * .35, new_sell_price, round_base, round_quote)
            update(product_id, 'sell_id', new_sell_id)
        else: print('Couldn\'t Cancel Sell Order For ' + product_id + ' because ' + get(product_id, 'sell_id'))
        
        
    def rebase(self, product_id, round_base, round_quote):
    # cancel orders
        r = requests.delete(api_url + '/orders', auth=auth, params={'product_id': product_id})
    # get all other parameters
        accounts = requests.get(api_url + '/accounts', auth=auth)
        currency_pair = product_id.partition('-')
        balance_as_list = [x['balance'] for x in accounts.json() if x['currency'] == currency_pair[0]]
        update(product_id, 'balance', float(balance_as_list[0]))
        
        update(product_id, 'running_avg', get(product_id, 'balance') * get(product_id, 'price'))
        
        with open("money_limits.json", "r") as f:
            limits = json.load(f)
        money_limit = limits[product_id]
    # place orders
        new_sell_id, new_stop_loss_id = place_orders(product_id, get(product_id, 'price'), get(product_id, 'balance'), money_limit, round_base, round_quote)
        update(product_id, 'sell_id', new_sell_id)
        update(product_id, 'stop_loss_id', new_stop_loss_id)
        
    def get_precision(self, product_id):
    # get what decimal to round size and price to
        product = requests.get(api_url + '/products/' + product_id, auth=auth)  
        base_min_size = product.json()['base_min_size']
        base_increment = product.json()['base_increment'].partition('.')
        quote_increment = product.json()['quote_increment'].partition('.')
        if base_increment[0] != '0':
            round_base = 0
        else: round_base = len(base_increment[2])

        if quote_increment[0] != '0':
            round_quote = 0
        else: round_quote = len(quote_increment[2])  
        return round_base, round_quote
    
    def on_message(self, message):
        if message['type'] == 'subscriptions': return
        # print(message)
        # get product id
        product_id = message['product_id']
        if 'trade_id' in message.keys():
            update(product_id, 'price', float(message['price']))
        if 'reason' in message.keys() and message['reason'] == "filled":
            # print message
            print(json.dumps(message, indent=4))
            # return if stop loss
            if message['order_id'] == get(product_id, 'stop_loss_id'):
                    print('stop loss triggered')
                    msg = EmailMessage()
                    msg.set_content(f'The stop loss for {message["product_id"]} has been triggered!')
                    send_email(msg, 'Subject: A Stop Loss has been triggered!')
                    return
            round_base, round_quote = self.get_precision(product_id)  
#                 -------------------------------------------
            if message['side'] == "sell":
                self.rebase(product_id, round_base, round_quote)
#                 -------------------------------------------
            elif message['side'] == "buy":
                self.change_sell_order(product_id, round_base, round_quote)
        else: return 
            
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    channel = Channel('user', tracking)
    ticker = Ticker(loop, channel, auth=True, key=API_KEY, secret=SECRET_KEY, passphrase=API_PASSPHRASE)
    print('started')
    try:
        loop.run_forever()
    except RuntimeError:
        pass
    except KeyboardInterrupt:
        loop.run_until_complete(ticker.close())
        loop.close()