import pytest
from brownie import config
from brownie import Contract


@pytest.fixture
def gov(accounts):
    yield accounts.at("0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52", force=True)


@pytest.fixture
def user(accounts):
    yield accounts[0]


@pytest.fixture
def rewards(accounts):
    yield accounts[1]


@pytest.fixture
def guardian(accounts):
    yield accounts[2]


@pytest.fixture
def management(accounts):
    yield accounts[3]


@pytest.fixture
def strategist(accounts):
    yield accounts[4]


@pytest.fixture
def keeper(accounts):
    yield accounts[5]


@pytest.fixture(
    params=["DAI", "SUSD", "USDC", "USDT", "WETH",]
)
def token(Token, request):
    tokens = {
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "SUSD": "0x57Ab1ec28D129707052df4dF418D58a2D46d5f51",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    }
    yield Token.at(tokens[request.param])


@pytest.fixture
def transferAmount(accounts, token):
    tokenWhales = {
        "0x6B175474E89094C44Da98b954EedeAC495271d0F": "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf",
        "0x57Ab1ec28D129707052df4dF418D58a2D46d5f51": "0x1f2c3a1046c32729862fcb038369696e3273a516",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48": "0xf977814e90da44bfa03b6295a0616a897441acec",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "0x2f0b23f53734252bda2277357e97e1517d6b042a",
    }

    def t(user, amount):
        reserve = accounts.at(tokenWhales[token.address], force=True)
        token.transfer(user, amount, {"from": reserve})
        return amount

    yield t


@pytest.fixture
def amount(transferAmount, token, user):
    amount = 10_000 * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate an exchange address to use it's funds.
    yield transferAmount(user, amount)


@pytest.fixture
def weth():
    token_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    yield Contract(token_address)


@pytest.fixture
def ubi():
    yield Contract("0xDd1Ad9A21Ce722C151A836373baBe42c868cE9a4")


@pytest.fixture
def uniswapRouter():
    yield Contract("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")


@pytest.fixture
def uniswapFactory():
    yield Contract("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f")


@pytest.fixture
def healthCheck(Contract):
    yield Contract("0xDDCea799fF1699e98EDF118e0629A974Df7DF012")


@pytest.fixture
def weth_amout(user, weth):
    weth_amout = 10 * 1e18
    user.transfer(weth, weth_amout)
    yield weth_amout


@pytest.fixture
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    yield vault


@pytest.fixture
def underlyingVault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian)
    vault.setDepositLimit(2 ** 256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    yield vault


@pytest.fixture
def strategy(strategist, keeper, vault, strategyDeployer, gov):
    strategy = strategyDeployer(vault)
    strategy.setKeeper(keeper)
    vault.addStrategy(strategy, 10_000, 0, 2 ** 256 - 1, 1_000, {"from": gov})
    yield strategy


@pytest.fixture
def strategyDeployer(
    strategist,
    underlyingVault,
    weth,
    uniswapRouter,
    uniswapFactory,
    ubi,
    AssetBurnStrategy,
    healthCheck,
    gov,
):
    def s(vault, proxy=True):
        strategy = strategist.deploy(
            AssetBurnStrategy,
            vault,
            underlyingVault,
            ubi,
            weth,
            uniswapRouter,
            uniswapFactory,
        )

        if proxy:
            tx = strategy.clone(
                vault,
                strategist,
                underlyingVault,
                ubi,
                weth,
                uniswapRouter,
                uniswapFactory,
            )

            strategy = AssetBurnStrategy.at(
                tx.events["Cloned"]["clone"], owner=strategist
            )

        strategy.setTargetSupply(ubi.totalSupply() / 2, {"from": gov})
        strategy.setHealthCheck(healthCheck, {"from": gov})
        strategy.setDoHealthCheck(True, {"from": gov})

        return strategy

    yield s


@pytest.fixture(scope="session")
def RELATIVE_APPROX():
    yield 1e-5
