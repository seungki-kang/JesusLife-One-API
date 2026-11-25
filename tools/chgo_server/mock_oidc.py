"""Local protocol fixture only; never used by an application entrypoint."""
import hashlib
import secrets
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4
import httpx
from app.core.auth0_poc import pkce_challenge
from app.core.auth0_provider import Auth0Provider
from tests.auth_contract_fixtures import SyntheticJWTs,NOW,b64url

class LocalOIDC:
    def __init__(self,config):
        self.config=config;self.jwt=SyntheticJWTs();self.codes={};self.issued={};self.exchanges=0
        self.provider=Auth0Provider(config,transport=httpx.MockTransport(self.handle))
    def issue(self,location,subject,*,wrong_nonce=False):
        q={k:v[0] for k,v in parse_qs(urlsplit(location).query).items()}
        if q.get('code_challenge_method')!='S256':raise RuntimeError('Expected PKCE S256')
        code=secrets.token_urlsafe(32);self.codes[code]=q|{'subject':subject,'wrong_nonce':wrong_nonce}
        return code,q['state']
    def handle(self,request):
        if request.url.host!=urlsplit(self.config.policy.issuer).hostname:return httpx.Response(400)
        if request.url.path=='/.well-known/jwks.json':
            key=self.jwt.public_key.public_numbers()
            def enc(n):return b64url(n.to_bytes((n.bit_length()+7)//8,'big'))
            return httpx.Response(200,json={'keys':[{'kid':'synthetic-key','kty':'RSA','alg':'RS256','use':'sig','n':enc(key.n),'e':enc(key.e)}]})
        if request.url.path!='/oauth/token' or request.method!='POST':return httpx.Response(404)
        form={k:v[0] for k,v in parse_qs(request.content.decode()).items()}
        query=self.codes.pop(form.get('code'),None)
        if not query or form.get('client_secret')!=self.config.client_secret or form.get('client_id')!=query['client_id'] or form.get('redirect_uri')!=query['redirect_uri'] or form.get('grant_type')!='authorization_code' or pkce_challenge(form.get('code_verifier',''))!=query['code_challenge']:
            return httpx.Response(400,json={'error':'invalid_grant'})
        self.exchanges+=1
        common={'iss':self.config.policy.issuer,'sub':query['subject'],'iat':NOW,'exp':NOW+600}
        raw=self.jwt.signed(claims=common|{'aud':self.config.policy.audience,'client_id':form['client_id'],'jti':str(uuid4()),'scope':query['scope']},omit=('azp','token_use'))
        identity=self.jwt.signed(header={'typ':'JWT'},claims=common|{'aud':form['client_id'],'nonce':'wrong' if query['wrong_nonce'] else query['nonce'],'at_hash':b64url(hashlib.sha256(raw.encode()).digest()[:16])},omit=('azp',))
        self.issued[query['subject']]=raw
        return httpx.Response(200,json={'access_token':raw,'id_token':identity,'token_type':'Bearer'})
