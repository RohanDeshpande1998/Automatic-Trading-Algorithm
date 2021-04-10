def authentication():
    accountID, token = None, None
    with open("account.txt") as I:
        accountID = I.read().strip()
        print(accountID)
    with open("token.txt") as I:
        token = I.read().strip()
    return accountID, token