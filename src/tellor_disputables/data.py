from dataclasses import dataclass
import json
import uuid
import random
from web3 import Web3
import os
from telliot_core.directory import contract_directory
import asyncio
from datetime import datetime
from dateutil import tz
from telliot_core.queries.abi_query import AbiQuery
from telliot_core.queries.json_query import JsonQuery
from tellor_disputables import EXAMPLE_NEW_REPORT_EVENT
from typing import Optional
from telliot_core.queries.legacy_query import LegacyRequest
from telliot_core.api import SpotPrice
from tellor_disputables import DATAFEED_LOOKUP
from tellor_disputables import LEGACY_ASSETS, LEGACY_CURRENCIES
from tellor_disputables.utils import get_tx_explorer_url
from tellor_disputables import CONFIDENCE_THRESHOLD
from tellor_disputables.utils import disputable_str


def get_infura_node_url(chain_id: int) -> str:
    urls = {
        1: "https://mainnet.infura.io/v3/",
        4: "https://rinkeby.infura.io/v3/",
        137: "https://polygon-mainnet.infura.io/v3/",
        80001: "https://polygon-mumbai.infura.io/v3/",
    }
    return f'{urls[chain_id]}{os.environ.get("INFURA_API_KEY")}'


def get_contract_info(chain_id):
    name = "tellorx-oracle" if chain_id in (1, 4) else "tellorflex-oracle"
    contract_info = contract_directory.find(chain_id=chain_id, name=name)[0]
    addr = contract_info.address[chain_id]
    abi = contract_info.get_abi(chain_id=chain_id)
    return addr, abi


def get_web3(chain_id: int):
    node_url = get_infura_node_url(chain_id)
    return Web3(Web3.HTTPProvider(node_url))


def get_contract(web3, addr, abi):
    return web3.eth.contract(
        address=addr,
        abi=abi,
    )


# asynchronous defined function to loop
# this loop sets up an event filter and is looking for new entires for the "PairCreated" event
# this loop runs on a poll interval
async def eth_log_loop(event_filter, poll_interval, chain_id):
    # while True:
    unique_events = {}
    unique_events_lis = []
    for event in event_filter.get_new_entries():
        txhash = event["transactionHash"]
        if txhash not in unique_events:
            unique_events[txhash] = event
            unique_events_lis.append((chain_id, event))
        # await asyncio.sleep(poll_interval)
    return unique_events_lis


async def poly_log_loop(web3, addr): #, event_filter, poll_interval, chain_id, loop_name):
    # while True:
    num = web3.eth.get_block_number()
    events = web3.eth.get_logs({
        'fromBlock':num,
        'toBlock': num+100,
        'address':addr
    })

    unique_events = {}
    unique_events_lis = []
    for event in events:
        txhash = event["transactionHash"]
        if txhash not in unique_events:
            unique_events[txhash] = event
            unique_events_lis.append((web3.eth.chain_id, event))
            # print('LOOP NAME:', loop_name)
            # handle_event(event)
        # await asyncio.sleep(poll_interval)
    
    return unique_events_lis


# def is_disputable(reported_val, trusted_val, conf_threshold):
def is_disputable(reported_val: float, query_id: str, conf_threshold: float) -> Optional[bool]:
    if query_id not in DATAFEED_LOOKUP:
        print(f"new report for unsupported query ID: {query_id}")
        return None
    current_feed = DATAFEED_LOOKUP[query_id]
    trusted_val = asyncio.run(current_feed.source.fetch_new_datapoint())[0]

    # print("reported val: ", reported_val, " trusted val: ", trusted_val)
    percent_diff = (reported_val - trusted_val) / trusted_val
    # print("percent_diff: ", percent_diff)
    return abs(percent_diff) > conf_threshold



@dataclass
class NewReport:
    tx_hash: str
    eastern_time: str
    chain_id: int
    link: str
    query_type: str 
    value: float 
    asset: str
    currency: str
    query_id: str
    disputable: Optional[bool]
    status_str: str


def timestamp_to_eastern(timestamp: int) -> str:
    est = tz.gettz("EST")
    dt = datetime.fromtimestamp(timestamp).astimezone(est)

    return str(dt)


def get_new_report(event_json: str):
    event = json.loads(event_json)
    event = {
        "txhash": uuid.uuid4().hex,
        "value": f"${round(random.uniform(2000, 3500), 2)}",
        "chain_id": random.choice([1, 137]),
        "query_type": "SpotPrice"
    }
    return NewReport(
        event["txhash"],
        event["value"],
        event["chain_id"],
        query_type=event["query_type"],
    )


def create_eth_event_filter(web3, addr, abi):
    contract = get_contract(web3, addr, abi)
    return contract.events.NewReport.createFilter(fromBlock='latest')


def create_polygon_event_filter(chain_id):
    return None


async def get_events(eth_web3, eth_oracle_addr, eth_abi, poly_web3, poly_oracle_addr):
    eth_mainnet_filter = create_eth_event_filter(eth_web3, eth_oracle_addr, eth_abi)
    # eth_testnet_filter = create_eth_event_filter(4)
    # polygon_mainnet_filter = create_polygon_event_filter(137)
    # polygon_testnet_filter = create_polygon_event_filter(80001)

    events_lists = await asyncio.gather(
                eth_log_loop(eth_mainnet_filter, 1, chain_id=1),
                # eth_log_loop(eth_testnet_filter, 2),
                # poly_log_loop(polygon_mainnet_filter, 2, 137, "tammy"),
                poly_log_loop(poly_web3, poly_oracle_addr),
    )
    return events_lists


def get_tx_receipt(tx_hash, web3, contract):
    receipt = web3.eth.getTransactionReceipt(tx_hash)
    receipt = contract.events.NewReport().processReceipt(receipt)[0]
    return receipt


def get_query_from_data(query_data):
    q = None
    for q_type in (AbiQuery, JsonQuery):
        try:
            q = q_type.get_query_from_data(query_data)
        except:
            continue
    return q


def get_legacy_request_pair_info(legacy_id: int):
    return LEGACY_ASSETS[legacy_id], LEGACY_CURRENCIES[legacy_id]


def parse_new_report_event(event, web3, contract) -> Optional[NewReport]:
    tx_hash = event['transactionHash']
    receipt = get_tx_receipt(tx_hash, web3, contract)
    if receipt["event"] != "NewReport":
        return None
    args = receipt["args"]
    q = get_query_from_data(args["_queryData"])

    if isinstance(q, SpotPrice):
        asset = q.asset.upper()
        currency = q.currency.upper()
    elif isinstance(q, LegacyRequest):
        asset, currency = get_legacy_request_pair_info(q.legacy_id)
    else:
        print('unsupported query type')
        return None

    val = q.value_type.decode(args["_value"])
    link = get_tx_explorer_url(
            tx_hash=tx_hash.hex(),
            chain_id=web3.eth.chain_id)
    query_id = str(q.query_id.hex())
    # Determine if value disputable
    disputable = is_disputable(val,query_id,CONFIDENCE_THRESHOLD)
    status_str = disputable_str(disputable, query_id)

    return NewReport(
        chain_id=web3.eth.chain_id,
        eastern_time=args["_time"],
        tx_hash=tx_hash.hex(),
        link=link,
        query_type=type(q).__name__,
        value=val,
        asset=asset,
        currency=currency,
        query_id=query_id,
        disputable=disputable,
        status_str = status_str
        )


def main():
    # _ = asyncio.run(get_events())
    poly_chain_id = 80001
    poly_web3 = get_web3(poly_chain_id)
    poly_addr, poly_abi = get_contract_info(poly_chain_id)
    poly_contract = get_contract(poly_web3, poly_addr, poly_abi)
    new_report = parse_new_report_event(
        EXAMPLE_NEW_REPORT_EVENT,
        poly_web3,
        poly_contract)
    print(new_report)
    


if __name__ == "__main__":
    main()