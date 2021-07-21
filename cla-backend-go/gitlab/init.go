package gitlab

var gitlabAppPrivateKey string
var gitlabAppID string

// Init initializes the required gitlab variables
func Init(glAppID string, glAppPrivateKey string) {
	gitlabAppPrivateKey = glAppPrivateKey
	gitlabAppID = glAppID
}

func getGitlabAppPrivateKey() string {
	return gitlabAppPrivateKey
}

func getGitlabAppID() string {
	return gitlabAppID
}
