import pytest
import brownie
from brownie import Wei
from brownie import config


def test_incorrect_vault(
    pm, guardian, gov, strategist, rewards, strategyDeployer, Token
):
    token = guardian.deploy(Token, 18)
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "")
    with brownie.reverts("Vault want is different from the underlying vault token"):
        strategy = strategyDeployer(vault)


def test_double_init(strategy, strategist):
    with brownie.reverts("Strategy already initialized"):
        strategy.init(
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
        )


def test_double_init_no_proxy(strategyDeployer, vault, strategist):
    strategy = strategyDeployer(vault, False)
    with brownie.reverts("Strategy already initialized"):
        strategy.init(
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
            strategist,
        )
