package gitlab

import (
	"github.com/communitybridge/easycla/cla-backend-go/config"
	"github.com/go-resty/resty/v2"
)

func FetchOauthCredentials(code string) (*OauthSuccessResponse, error) {
	client := resty.New()
	params := map[string]string{
		"client_id":     config.GetConfig().Gitlab.ClientID,
		"client_secret": config.GetConfig().Gitlab.ClientSecret,
		"code":          code,
		"grant_type":    "authorization_code",
		"redirect_uri":  config.GetConfig().Gitlab.RedirectURI,
	}

	resp, err := client.R().
		SetQueryParams(params).
		SetResult(&OauthSuccessResponse{}).
		Post("https://gitlab.com/oauth/token")

	if err != nil {
		return nil, err
	}

	return resp.Result().(*OauthSuccessResponse), nil
}
