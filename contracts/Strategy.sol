// SPDX-License-Identifier: AGPL-3.0
// Feel free to change the license, but this is what we use

// Feel free to change this version of Solidity. We support >=0.6.0 <0.7.0;
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

// These are the core Yearn libraries
import {
    BaseStrategy,
    StrategyParams,
    VaultAPI
} from "@yearnvaults/contracts/BaseStrategy.sol";
import {
    SafeERC20,
    SafeMath,
    Address
} from "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20Burnable.sol";
import "@openzeppelin/contracts/math/Math.sol";

import "../interfaces/Uniswap/IUniswapRouter.sol";


// Import interfaces for many popular DeFi projects, or add your own!
//import "../interfaces/<protocol>/<Interface>.sol";

contract Strategy is BaseStrategy {
    using SafeERC20 for ERC20;
    using Address for address;
    using SafeMath for uint256;

    VaultAPI public underlyingVault;
    address public ubi;
    address public weth;
    address public uniswapRouterV2;

    address[] internal _path;

    uint256 constant MAX_BPS = 10000;
    uint256 public burningProfitRatio;

    uint256 public targetSupply;

    modifier onlyGovernanceOrManagement() {
        require(msg.sender == governance() || msg.sender == vault.management(), "!authorized");
        _;
    }

    constructor(
        address _vault,
        address _underlyingVault,
        address _ubi,
        address _weth,
        address _uniswapRouterV2
    ) public BaseStrategy(_vault) {
        // You can set these parameters on deployment to whatever you want
        // maxReportDelay = 6300;
        // profitFactor = 100;
        // debtThreshold = 0;

        underlyingVault = VaultAPI(_underlyingVault);
        ubi = _ubi;

        weth = _weth;
        uniswapRouterV2 = _uniswapRouterV2;

        _path = new address[](3);
        _path[0] = address(want);
        _path[1] = weth; // TODO in the case underlying vault is weth drop
        _path[2] = ubi;
        ERC20(ubi).safeApprove(_uniswapRouterV2, type(uint256).max);

        // initial burning profit ratio 50%
        burningProfitRatio = 5000;

        // initial target supply equal to constructor initial supply
        targetSupply = ERC20(ubi).totalSupply();
        
        want.safeApprove(_underlyingVault, type(uint256).max);
    }

    // ******** OVERRIDE THESE METHODS FROM BASE CONTRACT ************

    function name() external view override returns (string memory) {
        // Add your own name here, suggestion e.g. "StrategyCreamYFI"
        return string(abi.encodePacked("StrategyUbi", ERC20(address(want)).symbol()));
    }

    /**
     * @notice
     *  The amount (priced in want) of the total assets managed by this strategy should not count
     *  towards Yearn's TVL calculations.
     * @dev
     *  You can override this field to set it to a non-zero value if some of the assets of this
     *  Strategy is somehow delegated inside another part of of Yearn's ecosystem e.g. another Vault.
     *  Note that this value must be strictly less than or equal to the amount provided by
     *  `estimatedTotalAssets()` below, as the TVL calc will be total assets minus delegated assets.
     *  Also note that this value is used to determine the total assets under management by this
     *  strategy, for the purposes of computing the management fee in `Vault`
     * @return
     *  The amount of assets this strategy manages that should not be included in Yearn's Total Value
     *  Locked (TVL) calculation across it's ecosystem.
     */
    function delegatedAssets() external override view returns (uint256) {
        return _balanceOnUnderlyingVault();
    }

    function estimatedTotalAssets() public view override returns (uint256) {
        return _balanceOfWant().add(_balanceOnUnderlyingVault());
    }

    function _balanceOfWant() internal view returns (uint256) {
        return ERC20(address(want)).balanceOf(address(this));
    }

    function _balanceOnUnderlyingVault() internal view returns (uint256) {
        return underlyingVault.balanceOf(address(this))
            .mul(underlyingVault.pricePerShare())
            .div(underlyingVault.decimals());
    }

    function ethToWant(uint256 _amount) internal view returns (uint256) {
        if (_amount == 0) {
            return 0;
        }

        address[] memory path = new address[](2);
        path[0] = address(weth);
        path[1] = address(want);
        uint256[] memory amounts = IUniswapRouter(uniswapRouterV2).getAmountsOut(_amount, path);

        return amounts[amounts.length - 1];
    }


    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        // TODO: Do stuff here to free up any returns back into `want`
        // NOTE: Return `_profit` which is value generated by all positions, priced in `want`
        // NOTE: Should try to free up at least `_debtOutstanding` of underlying position

        uint256 debt = vault.strategies(address(this)).totalDebt;
        uint256 currentValue = estimatedTotalAssets();
        uint256 wantBalance = _balanceOfWant();

        // Calculate total profit w/o farming
        if (debt < currentValue){
            _profit = currentValue.sub(debt);
        } else {
            _loss = debt.sub(currentValue);
        }

        // To withdraw = profit from lending + _debtOutstanding
        uint256 toFree = _debtOutstanding.add(_profit);

        // In the case want is not enough, divest from idle
        if (toFree > wantBalance) {
            // Divest only the missing part = toFree-wantBalance
            toFree = toFree.sub(wantBalance);
            (uint256 _liquidatedAmount, ) = liquidatePosition(toFree);

            // loss in the case freedAmount less to be freed
            uint256 withdrawalLoss = _liquidatedAmount < toFree ? toFree.sub(_liquidatedAmount) : 0;

            // profit recalc
            if (withdrawalLoss < _profit) {
                _profit = _profit.sub(withdrawalLoss);
            } else {
                _loss = _loss.add(withdrawalLoss.sub(_profit));
                _profit = 0;
            }
        }

        if (_profit > 0) {
            ERC20Burnable ubiToken = ERC20Burnable(ubi);
            uint256 currentTotalSupply = ubiToken.totalSupply();

            uint256 targetUbiToBurn = currentTotalSupply > targetSupply ?
                currentTotalSupply.sub(targetSupply) : 0; // supply <= targetSupply nothing to burn

            if (targetUbiToBurn > 0) {
                uint256 profitToConvert = _profit.mul(burningProfitRatio).div(MAX_BPS);

                IUniswapRouter router = IUniswapRouter(uniswapRouterV2);

                uint256 expectedProfitToUse = (router.getAmountsIn(targetUbiToBurn, _path))[0];

                // In the case profitToConvert > expected to use for burning target ubi use the latter
                // On the contrary use profitToConvert
                uint256 exchangedAmount = (router.swapExactTokensForTokens(
                    Math.min(profitToConvert, expectedProfitToUse), 
                    1, 
                    _path,
                    address(this), 
                    now.add(1800)
                ))[0];

                // TOBE CHECKED leverage uniswap returns want amount
                _profit = _profit.sub(exchangedAmount);

                // burn
                ubiToken.burn(ubiToken.balanceOf(address(this)));
            }
        }
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        // TODO: Do something to invest excess `want` tokens (from the Vault) into your positions
        // NOTE: Try to adjust positions so that `_debtOutstanding` can be freed up on *next* harvest (not immediately)
    
        //emergency exit is dealt with in prepareReturn
        if (emergencyExit) {
            return;
        }

        uint256 balanceOfWant = _balanceOfWant();
        if (balanceOfWant > _debtOutstanding) {
            underlyingVault.deposit(balanceOfWant.sub(_debtOutstanding));
        }
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        // TODO: Do stuff here to free up to `_amountNeeded` from all positions back into `want`

        uint256 balanceOfWant = _balanceOfWant();

        if (balanceOfWant < _amountNeeded) {
            uint256 amountToRedeem = _amountNeeded.sub(balanceOfWant);

            uint256 valueToRedeemApprox = amountToRedeem.mul(vault.decimals()).div(vault.pricePerShare());
            uint256 valueToRedeem = Math.min(
                valueToRedeemApprox,
                vault.balanceOf(address(this))
            );
            
            vault.withdraw(valueToRedeem);
        }

        // _liquidatedAmount min(_amountNeeded, balanceOfWant), otw vault accounting breaks
        balanceOfWant = _balanceOfWant();

        if (balanceOfWant >= _amountNeeded) {
            _liquidatedAmount = _amountNeeded;
        } else {
            _liquidatedAmount = balanceOfWant;
            _loss = _amountNeeded.sub(balanceOfWant);
        }
    }

    // NOTE: Can override `tendTrigger` and `harvestTrigger` if necessary

    function harvestTrigger(uint256 callCost) public view override returns (bool) {
        return super.harvestTrigger(ethToWant(callCost));
    }

    function prepareMigration(address _newStrategy) internal override {
        // TODO: Transfer any non-`want` tokens to the new strategy
        // NOTE: `migrate` will automatically forward all `want` in this strategy to the new one
    
        underlyingVault.withdraw();

        ERC20 ubiToken = ERC20(ubi);
        ubiToken.safeTransfer(_newStrategy, ubiToken.balanceOf(address(this)));
    }

    // Override this to add all tokens/tokenized positions this contract manages
    // on a *persistent* basis (e.g. not just for swapping back to want ephemerally)
    // NOTE: Do *not* include `want`, already included in `sweep` below
    //
    // Example:
    //
    //    function protectedTokens() internal override view returns (address[] memory) {
    //      address[] memory protected = new address[](3);
    //      protected[0] = tokenA;
    //      protected[1] = tokenB;
    //      protected[2] = tokenC;
    //      return protected;
    //    }
    function protectedTokens()
        internal
        view
        override
        returns (address[] memory)
    {
        address[] memory protected = new address[](1);

        protected[0] = ubi;

        return protected;
    }

    function setBurningProfitRatio(uint256 _burningProfitRatio)
        external
        onlyGovernanceOrManagement
    {
        require(_burningProfitRatio <= MAX_BPS, 'Burning profit ratio should be less than 10000');

        burningProfitRatio = _burningProfitRatio;
    }

    function setTargetSupply(uint256 _targetSuplly) 
        external
        onlyGovernanceOrManagement
    {
        targetSupply = _targetSuplly;
    }
}
