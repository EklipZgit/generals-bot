import traceback



def test_pickle_v2(xThing, lTested = [], typeChainConcat: str = ''):
    import pickle
    if id(xThing) in lTested:
        return lTested
    sType = type(xThing).__name__
    chain = f'{typeChainConcat}:{sType}'

    if sType in ['type','int','str', 'bool', 'NoneType', 'unicode']:
        # print('...too easy')
        return lTested

    print(f'Testing {chain} - {sType}...')

    if sType == 'dict':
        print(f'{chain} ...testing members v')
        for k in xThing:
            lTested = test_pickle_v2(xThing[k],lTested,f'{chain}["{str(k)}"]')
        print(f'{chain} ...finished members ^')
        return lTested
    if sType == 'list':
        print(f'{chain} ...testing members v')
        for i, x in enumerate(xThing):
            lTested = test_pickle_v2(x,lTested,f'{chain}[{i}]')
        print(f'{chain} ...finished members ^')
        return lTested

    lTested.append(id(xThing))
    oClass = type(xThing)

    thingState = xThing.__getstate__()
    if not isinstance(thingState, dict):
        thingState = dir(xThing)

    for s in thingState:
        attributeChain = f'{chain}.{s}'
        # if s.startswith('_'):
        #     print('...skipping *private* thingy')
        #     continue
        #if it is an attribute: Skip it
        try:
            xClassAttribute = oClass.__getattribute__(oClass,s)
        except (AttributeError, TypeError):
            pass
        else:
            if type(xClassAttribute).__name__ == 'property':
                print(f'{attributeChain} ...skipping property')
                continue

        xAttribute = xThing.__getattribute__(s)
        print(f'Testing {chain} -> {sType}.{s} of type {type(xAttribute).__name__}')
        if type(xAttribute).__name__ == 'function':
            print(f"{attributeChain} ...skipping function")
            continue
        if type(xAttribute).__name__ in ['method', 'instancemethod']:
            print(f'{attributeChain} ...skipping method')
            continue
        if type(xAttribute).__name__ == 'HtmlElement':
            continue
        if type(xAttribute) == dict:
            print(f'{attributeChain} ...testing dict values for {sType}.{s}')
            for k in xAttribute:
                lTested = test_pickle_v2(xAttribute[k], lTested, attributeChain)
                continue
            print(f'{attributeChain}  ...finished testing dict values for {sType}.{s}')

        try:
            oIter = xAttribute.__iter__()
        except (AttributeError, TypeError):
            pass
        except AssertionError:
            pass #lxml elements do this
        else:
            print(f'{attributeChain} ...testing iter values for {sType}.{s} of type {type(xAttribute).__name__}')
            for x in xAttribute:
                lTested = test_pickle_v2(x, lTested, attributeChain)
            print(f'{attributeChain} ...finished testing iter values for {sType}.{s}')

        try:
            xAttribute.__dict__
        except AttributeError:
            pass
        else:
            #this attribute should be explored seperately...
            lTested = test_pickle_v2(xAttribute, lTested, attributeChain)
            continue
        print(0, attributeChain, xThing, xAttribute)
        try:
            pickle.dumps(xAttribute)
        except:
            print(f'{attributeChain} -> xThing {xThing} attr {xAttribute} could not be serialized: {traceback.format_exc()}')

    print(f'{chain} -> Testing {sType} as complete object')
    pickle.dumps(xThing)
    return lTested