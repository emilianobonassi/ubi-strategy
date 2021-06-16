import brownie
from brownie import Contract
import pytest


def test_operation(
    accounts, token, vault, strategy, user, strategist, amount, chain, RELATIVE_APPROX
):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    assert token.balanceOf(vault.address) == amount

    # wait
    chain.sleep(10)

    # harvest
    strategy.harvest()
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # tend()
    strategy.tend()

    # withdrawal
    vault.withdraw({"from": user})
    assert (
        pytest.approx(token.balanceOf(user), rel=RELATIVE_APPROX) == user_balance_before
    )


def test_emergency_exit(
    accounts, token, vault, strategy, user, strategist, amount, chain, RELATIVE_APPROX
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # wait
    chain.sleep(10)

    strategy.harvest()
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # wait
    chain.sleep(10)

    # set emergency and exit
    strategy.setEmergencyExit()
    strategy.harvest()
    assert strategy.estimatedTotalAssets() < amount


def test_profitable_harvest(
    accounts,
    token,
    vault,
    strategy,
    user,
    strategist,
    amount,
    transferAmount,
    ubi,
    weth,
    RELATIVE_APPROX,
    chain,
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    assert token.balanceOf(vault.address) == amount

    # wait
    chain.sleep(10)

    # Harvest 1: Send funds through the strategy
    strategy.harvest()
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # TODO: Add some code before harvest #2 to simulate earning yield
    simulated = (100 if token.address != weth.address else 1) * (10 ** token.decimals())
    transferAmount(strategy.underlyingVault(), simulated)

    before_pps = vault.pricePerShare()

    # wait
    chain.sleep(10)

    # Harvest 2: Realize profit
    before_asset_supply = ubi.totalSupply()
    tx = strategy.harvest()
    chain.sleep(3600 * 6)  # 6 hrs needed for profits to unlock
    chain.mine(1)
    profit = token.balanceOf(vault.address)  # Profits go to vault

    assert strategy.estimatedTotalAssets() + profit > amount
    assert vault.pricePerShare() > before_pps

    # check swap the correct profit qty
    swapEvents = tx.events["Swap"]
    assert (
        pytest.approx(swapEvents[0]["amount0In"], rel=RELATIVE_APPROX)
        == strategy.burningProfitRatio() * simulated / 10_000
        or pytest.approx(swapEvents[0]["amount1In"], rel=RELATIVE_APPROX)
        == strategy.burningProfitRatio() * simulated / 10_000
    )

    # check burn the target asset qty
    # only for weth and dai the path is shorter otw we have two swaps via weth, the last swap is the asset qty bought
    assert swapEvents[tx.events.count("Swap") - 1]["amount1Out"] == (
        before_asset_supply - ubi.totalSupply()
    )


def test_change_debt(
    gov, token, vault, strategy, user, strategist, amount, chain, RELATIVE_APPROX
):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})

    # wait
    chain.sleep(10)

    strategy.harvest()
    half = int(amount / 2)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half

    # wait
    chain.sleep(10)

    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    strategy.harvest()
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # wait
    chain.sleep(10)

    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    strategy.harvest()
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half


def test_sweep(gov, vault, strategy, token, user, amount, weth, weth_amout):
    # Strategy want token doesn't work
    token.transfer(strategy, amount, {"from": user})
    assert token.address == strategy.want()
    assert token.balanceOf(strategy) > 0
    with brownie.reverts("!want"):
        strategy.sweep(token, {"from": gov})

    # Vault share token doesn't work
    with brownie.reverts("!shares"):
        strategy.sweep(vault.address, {"from": gov})

    with brownie.reverts("!protected"):
        strategy.sweep(strategy.asset(), {"from": gov})

    if weth.address != strategy.want():
        before_balance = weth.balanceOf(gov)
        weth.transfer(strategy, weth_amout, {"from": user})
        strategy.sweep(weth, {"from": gov})
        assert weth.balanceOf(gov) == weth_amout + before_balance


def test_triggers(
    gov, vault, strategy, token, amount, user, weth, weth_amout, strategist, chain
):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})

    # wait
    chain.sleep(10)

    strategy.harvest()

    strategy.harvestTrigger(0)
    strategy.tendTrigger(0)
