def check_risk(action, price, balance):
    # Rule: Never spend more than 10% of balance on one trade
    max_position = balance * 0.10
    if action == "BUY" and price > max_position:
        return False, "Trade too large for risk rules"
    return True, "Risk Approved"