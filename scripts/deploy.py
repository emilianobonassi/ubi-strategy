from pathlib import Path

from brownie import AssetBurnStrategy, accounts, config, network, project, web3
from eth_utils import is_checksum_address
import click

API_VERSION = config["dependencies"][0].split("@")[-1]
Vault = project.load(
    Path.home() / ".brownie" / "packages" / config["dependencies"][0]
).Vault


def get_address(msg: str, default: str = None) -> str:
    val = click.prompt(msg, default=default)

    # Keep asking user for click.prompt until it passes
    while True:

        if is_checksum_address(val):
            return val
        elif addr := web3.ens.address(val):
            click.echo(f"Found ENS '{val}' [{addr}]")
            return addr

        click.echo(
            f"I'm sorry, but '{val}' is not a checksummed address or valid ENS record"
        )
        # NOTE: Only display default once
        val = click.prompt(msg)


def main():
    print(f"You are using the '{network.show_active()}' network")
    dev = accounts.load(click.prompt("Account", type=click.Choice(accounts.load())))
    print(f"You are using: 'dev' [{dev.address}]")

    if input("Is there a Vault for this strategy already? y/[N]: ").lower() == "y":
        vault = Vault.at(get_address("Deployed Vault: "))
        assert vault.apiVersion() == API_VERSION
    else:
        print("You should deploy one vault using scripts from Vault project")
        return  # TODO: Deploy one using scripts from Vault project

    print(
        f"""
    Strategy Parameters

       api: {API_VERSION}
     token: {vault.token()}
      name: '{vault.name()}'
    symbol: '{vault.symbol()}'
    """
    )
    publish_source = click.confirm("Verify source on etherscan?")
    if input("Deploy Strategy? y/[N]: ").lower() != "y":
        return

    # Ask for IdleToken and check underlying is the same of the vault
    underlyingVault = Vault.at(get_address("Underlying Vault: "))
    assert underlyingVault.token() == vault.token()

    # Production mgr
    onBehalfOf = get_address("Strategist: ")
    asset = "0xDd1Ad9A21Ce722C151A836373baBe42c868cE9a4"
    weth = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    uniswapRouter = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    uniswapFactory = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"

    strategyLogic = ""
    if input("Is there a Strategy logic deployed? y/[N]: ").lower() != "y":
        if input("Deploy Strategy logic? y/[N]: ").lower() == "y":
            strategyLogic = AssetBurnStrategy.deploy(
                vault,
                underlyingVault,
                asset,
                weth,
                uniswapRouter,
                uniswapFactory,
                {"from": dev},
                publish_source=publish_source,
            )
            strategyLogic.setKeeper(onBehalfOf, {"from": dev})
            strategyLogic.setRewards(onBehalfOf, {"from": dev})
            strategyLogic.setStrategist(onBehalfOf, {"from": dev})
            return
        else:
            return
    else:
        strategyLogic = AssetBurnStrategy.at(get_address("Deployed logic: "))

    if input("Deploy Strategy? y/[N]: ").lower() != "y":
        return

    tx = strategyLogic.clone(
        vault,
        onBehalfOf,
        underlyingVault,
        asset,
        weth,
        uniswapRouter,
        uniswapFactory,
        {"from": dev},
    )

    strategyAddress = tx.events["Cloned"]["clone"]

    print(f"Strategy deployed at {strategyAddress}")
